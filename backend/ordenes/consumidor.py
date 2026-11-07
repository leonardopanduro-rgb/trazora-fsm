"""MS3: consumidor SQS de ParteFinalizado y VisitaCompletada.

Usa SNS -> SQS (entrega raw) y transacciones DynamoDB. No usa Streams.
ParteFinalizado registra resultado; SOLO VisitaCompletada actualiza estado de orden.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["ORDENES_TABLE"]
SQS_ARN = os.environ["SQS_ORDENES_ARN"]
TABLE = boto3.resource("dynamodb").Table(TABLE_NAME)
DYNAMODB = boto3.client("dynamodb")
SERIALIZER = TypeSerializer()

TENANTS = {"CLIMALIMA", "FRIOSUR", "TECNINORTE"}
RESULTADOS = {"RESUELTO", "REQUIERE_REVISITA", "NO_ATENDIDO"}
TIPOS = {"ParteFinalizado": "PARTE", "VisitaCompletada": "VISITA"}
ACTIVOS = {"ABIERTA", "PROGRAMADA", "EN_ATENCION", "REQUIERE_REVISITA", "PENDIENTE_DE_CIERRE"}
UUID = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


def av(item):
    return {k: SERIALIZER.serialize(v) for k, v in item.items()}


def validar(evento):
    if not isinstance(evento, dict) or not isinstance(evento.get("data"), dict):
        raise ValueError("Evento no es JSON con data")
    tipo = evento.get("event_type")
    datos = evento["data"]
    ids = [evento.get("event_id"), evento.get("aggregate_id"),
           datos.get("parte_id"), datos.get("visita_id"), datos.get("orden_id")]
    if not all(isinstance(i, str) and UUID.fullmatch(i) for i in ids):
        raise ValueError("Identificadores de evento invalidos")
    if (tipo not in TIPOS
            or evento.get("tenant_id") not in TENANTS
            or evento.get("aggregate_type") != TIPOS[tipo]
            or evento.get("aggregate_id") != datos["parte_id" if tipo == "ParteFinalizado" else "visita_id"]
            or evento.get("correlation_id") != datos["visita_id"]
            or type(evento.get("schema_version")) is not int
            or evento["schema_version"] != 1
            or type(evento.get("aggregate_version")) is not int
            or evento["aggregate_version"] < 2
            or datos.get("resultado") not in RESULTADOS):
        raise ValueError("Contrato de evento no admitido")
    fecha = evento.get("occurred_at")
    if not isinstance(fecha, str):
        raise ValueError("Falta occurred_at")
    try:
        momento = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
        if momento.tzinfo is None:
            raise ValueError("Fecha sin zona horaria")
    except ValueError as exc:
        raise ValueError("Fecha del evento invalida") from exc
    return momento.astimezone(timezone.utc).isoformat(timespec="microseconds")


def procesar(evento):
    ocurrido = validar(evento)
    datos, tenant = evento["data"], evento["tenant_id"]
    tipo, event_id = evento["event_type"], evento["event_id"]
    pk = "TENANT#" + tenant
    inbox_key = {"PK": pk, "SK": "INBOX#" + event_id}
    digest = hashlib.sha256(json.dumps(
        evento, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()

    previo = TABLE.get_item(Key=inbox_key, ConsistentRead=True).get("Item")
    if previo:
        if previo.get("payload_sha256") != digest:
            raise ValueError("event_id reutilizado con contenido diferente")
        return "duplicado"

    orden_key = {"PK": pk, "SK": "ORDEN#" + datos["orden_id"]}
    orden = TABLE.get_item(Key=orden_key, ConsistentRead=True).get("Item")
    if (not orden or orden.get("tenant_id") != tenant
            or orden.get("orden_id") != datos["orden_id"]):
        raise ValueError("Orden inexistente o de otro tenant")

    ahora = datetime.now(timezone.utc).isoformat()
    anterior = orden.get("ultimo_visita_completada_en")
    obsoleto = bool(tipo == "VisitaCompletada" and anterior and ocurrido < anterior)
    nuevo_estado = None
    if tipo == "VisitaCompletada" and not obsoleto and orden.get("estado") in ACTIVOS:
        nuevo_estado = ("PENDIENTE_DE_CIERRE" if datos["resultado"] == "RESUELTO"
                        else "ABIERTA")

    historial = {
        "PK": pk, "SK": f"HISTORIAL#{datos['orden_id']}#{event_id}",
        "entity_type": "HISTORIAL_ORDEN", "tenant_id": tenant,
        "orden_id": datos["orden_id"], "visita_id": datos["visita_id"],
        "parte_id": datos["parte_id"], "event_id": event_id,
        "event_type": tipo, "resultado": datos["resultado"],
        "ocurrido_en": ocurrido, "procesado_en": ahora,
        "obsoleto": obsoleto, "estado_anterior": orden.get("estado", ""),
    }
    actions = []
    if nuevo_estado is not None:
        actions.append({"Update": {
            "TableName": TABLE_NAME,
            "Key": av(orden_key),
            "UpdateExpression": (
                "SET #estado=:nuevo, ultimo_resultado=:resultado, ultimo_parte_id=:parte, "
                "ultima_visita_id=:visita, ultimo_evento_id=:id, "
                "ultimo_visita_completada_en=:fecha, requiere_revisita=:revisita, "
                "actualizado_en=:ahora"
            ),
            "ConditionExpression": (
                "#estado=:anterior AND tenant_id=:tenant AND orden_id=:orden "
                "AND (attribute_not_exists(ultimo_visita_completada_en) "
                "OR ultimo_visita_completada_en <= :fecha)"
            ),
            "ExpressionAttributeNames": {"#estado": "estado"},
            "ExpressionAttributeValues": av({
                ":nuevo": nuevo_estado, ":anterior": orden["estado"],
                ":tenant": tenant, ":orden": datos["orden_id"],
                ":resultado": datos["resultado"], ":parte": datos["parte_id"],
                ":visita": datos["visita_id"], ":id": event_id,
                ":fecha": ocurrido, ":revisita": datos["resultado"] != "RESUELTO",
                ":ahora": ahora,
            }),
        }})
    actions.extend([
        {"Put": {
            "TableName": TABLE_NAME,
            "Item": av(historial),
            "ConditionExpression": "attribute_not_exists(PK)",
        }},
        {"Put": {
            "TableName": TABLE_NAME,
            "Item": av({
                **inbox_key, "entity_type": "INBOX", "tenant_id": tenant,
                "event_id": event_id, "event_type": tipo,
                "payload_sha256": digest, "procesado_en": ahora,
            }),
            "ConditionExpression": "attribute_not_exists(PK)",
        }},
    ])
    try:
        DYNAMODB.transact_write_items(TransactItems=actions)
    except ClientError:
        # Un reintento concurrente del mismo evento puede haber terminado primero.
        previo = TABLE.get_item(Key=inbox_key, ConsistentRead=True).get("Item")
        if previo and previo.get("payload_sha256") == digest:
            return "duplicado"
        raise
    return "obsoleto" if obsoleto else "procesado"


def lambda_handler(event, context):
    registros = event.get("Records", [])
    if not isinstance(registros, list):
        raise ValueError("Records debe ser una lista")
    resultado = {"procesados": 0, "duplicados": 0, "obsoletos": 0}
    for registro in registros:
        try:
            if (registro.get("eventSource") != "aws:sqs"
                    or registro.get("eventSourceARN") != SQS_ARN):
                raise ValueError("Origen SQS inesperado")
            payload = json.loads(registro["body"])
            estado = procesar(payload)
            campo = {"procesado": "procesados", "duplicado": "duplicados",
                     "obsoleto": "obsoletos"}[estado]
            resultado[campo] += 1
            print(json.dumps({"tipo": "INFO", "resultado": estado,
                              "event_id": payload["event_id"],
                              "tenant_id": payload["tenant_id"]}))
        except Exception as exc:
            print(json.dumps({"tipo": "ERROR", "error": type(exc).__name__,
                              "message_id": registro.get("messageId")}))
            # batchSize=1: lanzar para reintento y eventual DLQ
            raise
    return resultado
