"""Consumidor manual SQS Órdenes: registra ParteFinalizado de forma idempotente.

Mismo esquema de evento que crea MS5; NO cierra órdenes por sí solo.
Requiere SQS raw message delivery, batch size 1 y rol con DynamoDB y SQS.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

ORDENES_TABLE = os.environ["ORDENES_TABLE"]
SQS_ORDENES_ARN = os.environ["SQS_ORDENES_ARN"]
DB = boto3.resource("dynamodb").Table(ORDENES_TABLE)
CLIENT = boto3.client("dynamodb")
SER = TypeSerializer()
TENANTS = frozenset(("CLIMALIMA", "FRIOSUR", "TECNINORTE"))
RESULTADOS = frozenset(("RESUELTO", "REQUIERE_REVISITA", "NO_ATENDIDO"))
UUID = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


def av(datos):
    return {k: SER.serialize(v) for k, v in datos.items()}


def validar(evento):
    if not isinstance(evento, dict) or not isinstance(evento.get("data"), dict):
        raise ValueError("Evento JSON inválido")
    datos = evento["data"]
    ids = (
        evento.get("event_id"), evento.get("aggregate_id"),
        datos.get("parte_id"), datos.get("visita_id"), datos.get("orden_id"),
    )
    if not all(isinstance(x, str) and UUID.fullmatch(x) for x in ids):
        raise ValueError("Identificadores UUID inválidos")
    if (
        evento.get("event_type") != "ParteFinalizado"
        or evento.get("tenant_id") not in TENANTS
        or evento.get("aggregate_type") != "PARTE"
        or evento.get("aggregate_id") != datos["parte_id"]
        or evento.get("correlation_id") != datos["visita_id"]
        or type(evento.get("schema_version")) is not int
        or evento["schema_version"] != 1
        or type(evento.get("aggregate_version")) is not int
        or evento["aggregate_version"] < 2
        or datos.get("resultado") not in RESULTADOS
    ):
        raise ValueError("Contrato ParteFinalizado no válido")

    fecha = evento.get("occurred_at")
    if not isinstance(fecha, str):
        raise ValueError("Falta fecha del evento")
    try:
        dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Falta zona UTC")
    except ValueError as exc:
        raise ValueError("Fecha inválida") from exc
    ocurrido = dt.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return evento, ocurrido


def procesar(evento):
    evento, ocurrido = validar(evento)
    tenant = evento["tenant_id"]
    datos = evento["data"]
    evento_id = evento["event_id"]
    pk = f"TENANT#{tenant}"
    inbox_key = {"PK": pk, "SK": f"INBOX#{evento_id}"}
    digest = hashlib.sha256(
        json.dumps(
            evento, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()

    inbox = DB.get_item(Key=inbox_key, ConsistentRead=True).get("Item")
    if inbox:
        if inbox.get("payload_sha256") != digest:
            raise ValueError("Event ID reutilizado con contenido diferente")
        return "duplicado"

    orden_key = {"PK": pk, "SK": f"ORDEN#{datos['orden_id']}"}
    orden = DB.get_item(Key=orden_key, ConsistentRead=True).get("Item")
    if (
        not orden or orden.get("orden_id") != datos["orden_id"]
        or orden.get("tenant_id") != tenant
    ):
        raise ValueError("Orden inexistente o de otra empresa")

    estado_actual = orden.get("estado")
    if estado_actual not in ("ABIERTA", "REQUIERE_REVISITA", "PENDIENTE_DE_CIERRE"):
        raise ValueError("Orden cerrada, cancelada o de estado incompatible")

    anterior = orden.get("ultimo_evento_ocurrido_en")
    if anterior is not None and anterior > ocurrido:
        raise ValueError("Evento antiguo respecto a la orden; revisar cronología")

    # Una orden solo se puede cerrar después de verificar el flujo completo.
    # Si requiere nueva visita, mantener ABIERTA para que MS4 pueda programarla.
    requiere_revisita = datos["resultado"] != "RESUELTO"
    estado_nuevo = "ABIERTA" if requiere_revisita else "PENDIENTE_DE_CIERRE"
    ahora = datetime.now(timezone.utc).isoformat()
    historial = {
        "PK": pk,
        "SK": f"HISTORIAL#{datos['orden_id']}#{evento_id}",
        "entity_type": "HISTORIAL_ORDEN",
        "tenant_id": tenant,
        "orden_id": datos["orden_id"],
        "visita_id": datos["visita_id"],
        "parte_id": datos["parte_id"],
        "event_id": evento_id,
        "event_type": "ParteFinalizado",
        "resultado": datos["resultado"],
        "estado_anterior": estado_actual,
        "estado_nuevo": estado_nuevo,
        "ocurrido_en": ocurrido,
        "procesado_en": ahora,
    }
    inbox_item = {
        **inbox_key,
        "entity_type": "INBOX",
        "tenant_id": tenant,
        "event_id": evento_id,
        "event_type": "ParteFinalizado",
        "payload_sha256": digest,
        "procesado_en": ahora,
    }

    # Las tres acciones deben ser atómicas: orden + historial + INBOX.
    actions = [
        {"Update": {
            "TableName": ORDENES_TABLE,
            "Key": av(orden_key),
            "UpdateExpression": (
                "SET #estado = :nuevo, ultimo_resultado = :resultado, "
                "ultimo_parte_id = :parte, ultima_visita_id = :visita, "
                "ultimo_evento_id = :evento_id, "
                "ultimo_evento_ocurrido_en = :ocurrido, "
                "requiere_revisita = :revisita, actualizado_en = :ahora"
            ),
            "ConditionExpression": (
                "attribute_exists(PK) AND #estado = :anterior "
                "AND tenant_id = :tenant AND orden_id = :orden "
                "AND (attribute_not_exists(ultimo_evento_ocurrido_en) "
                "OR ultimo_evento_ocurrido_en <= :ocurrido)"
            ),
            "ExpressionAttributeNames": {"#estado": "estado"},
            "ExpressionAttributeValues": av({
                ":nuevo": estado_nuevo,
                ":anterior": estado_actual,
                ":tenant": tenant,
                ":orden": datos["orden_id"],
                ":resultado": datos["resultado"],
                ":parte": datos["parte_id"],
                ":visita": datos["visita_id"],
                ":evento_id": evento_id,
                ":ocurrido": ocurrido,
                ":revisita": requiere_revisita,
                ":ahora": ahora,
            }),
        }},
        {"Put": {
            "TableName": ORDENES_TABLE,
            "Item": av(historial),
            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
        }},
        {"Put": {
            "TableName": ORDENES_TABLE,
            "Item": av(inbox_item),
            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
        }},
    ]
    try:
        CLIENT.transact_write_items(TransactItems=actions)
    except ClientError:
        # Solo reintento idéntico con mismo hash cuenta como duplicado.
        inbox = DB.get_item(Key=inbox_key, ConsistentRead=True).get("Item")
        if inbox and inbox.get("payload_sha256") == digest:
            return "duplicado"
        raise
    return "actualizado"


def lambda_handler(event, context):
    registros = event.get("Records", [])
    if not isinstance(registros, list):
        raise ValueError("Records debe ser una lista")
    totales = {"procesados": 0, "duplicados": 0}
    for registro in registros:
        try:
            if (registro.get("eventSource") != "aws:sqs"
                    or registro.get("eventSourceARN") != SQS_ORDENES_ARN):
                raise ValueError("Origen SQS no autorizado")
            mensaje = json.loads(registro["body"])
            resultado = procesar(mensaje)
            totales["procesados" if resultado == "actualizado" else "duplicados"] += 1
            print(json.dumps({
                "tipo": "INFO", "resultado": resultado,
                "event_id": mensaje["event_id"],
                "tenant_id": mensaje["tenant_id"],
            }))
        except Exception as exc:
            print(json.dumps({
                "tipo": "ERROR", "error": type(exc).__name__,
                "message_id": registro.get("messageId"),
            }))
            # Batch size 1: cualquier fallo fuerza el reintento SQS/DLQ.
            raise
    return totales
