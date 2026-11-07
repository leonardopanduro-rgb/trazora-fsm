"""MS4: consumidor SQS; confirma visita y publica VisitaCompletada via SNS.

OUTBOX de Agenda e INBOX se guardan en transaccion con la visita.
No se usan DynamoDB Streams. Ante error de SNS, SQS reintenta y
un script de recuperacion puede publicar los OUTBOX pendientes.
"""
import hashlib
import json
import os
import re
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["AGENDA_TABLE"]
SQS_ARN = os.environ["SQS_AGENDA_ARN"]
TOPIC_ARN = os.environ["EVENTOS_TOPIC_ARN"]
TABLE = boto3.resource("dynamodb").Table(TABLE_NAME)
DYNAMODB = boto3.client("dynamodb")
SNS = boto3.client("sns")
SERIALIZER = TypeSerializer()

TENANTS = {"CLIMALIMA", "FRIOSUR", "TECNINORTE"}
RESULTADOS = {"RESUELTO", "REQUIERE_REVISITA", "NO_ATENDIDO"}
UUID = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
FECHA = "%Y-%m-%dT%H:%M:%SZ"


def serializar_decimal(value):
    """DynamoDB entrega números como Decimal; mantener enteros JSON numéricos."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("Decimal no finito")
        if value == value.to_integral_value():
            return int(value)
        return str(value)
    raise TypeError(f"No se puede serializar {type(value).__name__}")


def av(item):
    return {k: SERIALIZER.serialize(v) for k, v in item.items()}


def validar(evento):
    if not isinstance(evento, dict) or not isinstance(evento.get("data"), dict):
        raise ValueError("Evento JSON invalido")
    d = evento["data"]
    ids = [evento.get("event_id"), evento.get("aggregate_id"),
           d.get("parte_id"), d.get("visita_id"), d.get("orden_id")]
    if not all(isinstance(x, str) and UUID.fullmatch(x) for x in ids):
        raise ValueError("UUID invalido")
    if (evento.get("event_type") != "ParteFinalizado"
            or evento.get("tenant_id") not in TENANTS
            or evento.get("aggregate_type") != "PARTE"
            or evento.get("aggregate_id") != d["parte_id"]
            or evento.get("correlation_id") != d["visita_id"]
            or type(evento.get("schema_version")) is not int
            or evento["schema_version"] != 1
            or type(evento.get("aggregate_version")) is not int
            or evento["aggregate_version"] < 2
            or d.get("resultado") not in RESULTADOS):
        raise ValueError("Contrato ParteFinalizado invalido")
    fecha = evento.get("occurred_at")
    if not isinstance(fecha, str):
        raise ValueError("Fecha ausente")
    try:
        dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Fecha sin zona")
    except ValueError as exc:
        raise ValueError("Fecha invalida") from exc
    return evento


def bloques(visita):
    try:
        inicio = datetime.strptime(visita["inicio"], FECHA).replace(tzinfo=timezone.utc)
        fin = datetime.strptime(visita["fin"], FECHA).replace(tzinfo=timezone.utc)
        tecnico = visita["tecnico_id"]
        if not isinstance(tecnico, str) or not UUID.fullmatch(tecnico):
            raise ValueError("Tecnico invalido")
        duracion = (fin - inicio).total_seconds()
        if (not 1800 <= duracion <= 14400 or duracion % 1800
                or inicio.minute not in (0, 30) or fin.minute not in (0, 30)):
            raise ValueError("Horario de visita inconsistente")
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Bloques invalidos") from exc
    salida = []
    cursor = inicio
    while cursor < fin:
        salida.append(f"BLOQUE#{tecnico}#{cursor.strftime(FECHA)}")
        cursor += timedelta(minutes=30)
    return salida


def id_completada(evento):
    # Id estable aun si SQS entrega el mismo ParteFinalizado varias veces.
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"trazora:{evento['tenant_id']}:{evento['event_id']}:VisitaCompletada"
    ))


def procesar(evento):
    validar(evento)
    d, tenant = evento["data"], evento["tenant_id"]
    pk, eid = "TENANT#" + tenant, evento["event_id"]
    inbox_key = {"PK": pk, "SK": "INBOX#" + eid}
    nuevo_id = id_completada(evento)
    outbox_key = {"PK": pk, "SK": "OUTBOX#" + nuevo_id}
    digest = hashlib.sha256(json.dumps(
        evento, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()

    previo = TABLE.get_item(Key=inbox_key, ConsistentRead=True).get("Item")
    if previo:
        if previo.get("payload_sha256") != digest:
            raise ValueError("event_id reutilizado con otro contenido")
        return "duplicado", outbox_key

    llave_visita = {"PK": pk, "SK": "VISITA#" + d["visita_id"]}
    visita = TABLE.get_item(Key=llave_visita, ConsistentRead=True).get("Item")
    if (not visita or visita.get("tenant_id") != tenant
            or visita.get("visita_id") != d["visita_id"]
            or visita.get("orden_id") != d["orden_id"]
            or visita.get("estado") != "EN_ATENCION"):
        raise ValueError("Visita no encontrada o no finalizable")
    version = visita.get("version")
    if (isinstance(version, bool) or not isinstance(version, (int, Decimal))
            or version < 1 or int(version) != version):
        raise ValueError("Version de visita invalida")

    ahora = datetime.now(timezone.utc).strftime(FECHA)
    completada = {
        "event_id": nuevo_id,
        "event_type": "VisitaCompletada",
        "schema_version": 1,
        "tenant_id": tenant,
        "aggregate_type": "VISITA",
        "aggregate_id": d["visita_id"],
        "aggregate_version": int(visita["version"]) + 1,
        "occurred_at": ahora,
        "correlation_id": d["visita_id"],
        "data": {
            "visita_id": d["visita_id"],
            "orden_id": d["orden_id"],
            "parte_id": d["parte_id"],
            "resultado": d["resultado"],
        },
    }

    actions = [
        {"Update": {
            "TableName": TABLE_NAME,
            "Key": av(llave_visita),
            "UpdateExpression": "SET #estado=:finalizada, finalizada_en=:ahora ADD #version :uno",
            "ConditionExpression": (
                "#estado=:atencion AND tenant_id=:tenant AND visita_id=:visita "
                "AND orden_id=:orden AND tecnico_id=:tecnico AND inicio=:inicio AND fin=:fin "
                "AND #version=:esperada"
            ),
            "ExpressionAttributeNames": {"#estado": "estado", "#version": "version"},
            "ExpressionAttributeValues": av({
                ":finalizada": "FINALIZADA", ":atencion": "EN_ATENCION",
                ":tenant": tenant, ":visita": d["visita_id"],
                ":orden": d["orden_id"], ":tecnico": visita["tecnico_id"],
                ":inicio": visita["inicio"], ":fin": visita["fin"],
                ":ahora": ahora, ":uno": 1, ":esperada": version,
            }),
        }}
    ]
    for sk in bloques(visita):
        actions.append({"Delete": {
            "TableName": TABLE_NAME,
            "Key": av({"PK": pk, "SK": sk}),
            "ConditionExpression": "visita_id=:visita AND tecnico_id=:tecnico",
            "ExpressionAttributeValues": av({
                ":visita": d["visita_id"], ":tecnico": visita["tecnico_id"],
            }),
        }})
    actions.extend([
        {"Update": {
            "TableName": TABLE_NAME,
            "Key": av({"PK": pk, "SK": "CONTROL_ORDEN#" + d["orden_id"]}),
            "UpdateExpression": "ADD visitas_activas :menos",
            "ConditionExpression": (
                "attribute_exists(PK) AND orden_id=:orden AND visitas_activas >= :uno"
            ),
            "ExpressionAttributeValues": av({
                ":orden": d["orden_id"], ":menos": -1, ":uno": 1,
            }),
        }},
        {"Put": {
            "TableName": TABLE_NAME,
            "Item": av({
                **inbox_key, "entity_type": "INBOX", "tenant_id": tenant,
                "event_id": eid, "event_type": "ParteFinalizado",
                "payload_sha256": digest, "procesado_en": ahora,
            }),
            "ConditionExpression": "attribute_not_exists(PK)",
        }},
        {"Put": {
            "TableName": TABLE_NAME,
            "Item": av({
                **outbox_key, "entity_type": "OUTBOX",
                "tenant_id": tenant, "event_id": nuevo_id,
                "event_type": "VisitaCompletada", "payload": completada,
                "estado": "PENDIENTE", "creado_en": ahora,
            }),
            "ConditionExpression": "attribute_not_exists(PK)",
        }},
    ])
    try:
        DYNAMODB.transact_write_items(TransactItems=actions)
    except ClientError:
        previo = TABLE.get_item(Key=inbox_key, ConsistentRead=True).get("Item")
        if previo and previo.get("payload_sha256") == digest:
            return "duplicado", outbox_key
        raise
    return "finalizado", outbox_key


def publicar_outbox(llave):
    item = TABLE.get_item(Key=llave, ConsistentRead=True).get("Item")
    if not item or item.get("entity_type") != "OUTBOX":
        raise ValueError("OUTBOX de VisitaCompletada no encontrado")
    if item.get("estado") == "PUBLICADO":
        return "publicado_previamente"
    if item.get("estado") != "PENDIENTE":
        raise ValueError("OUTBOX con estado incompatible")
    payload = item["payload"]
    if (item.get("tenant_id") != payload.get("tenant_id")
            or item.get("event_id") != payload.get("event_id")
            or payload.get("event_type") != "VisitaCompletada"):
        raise ValueError("OUTBOX inconsistente")
    # Tal como en el taller SNS: publicar JSON en el topic con boto3.
    SNS.publish(
        TopicArn=TOPIC_ARN,
        Message=json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                           default=serializar_decimal),
    )
    try:
        TABLE.update_item(
            Key=llave,
            UpdateExpression="SET #estado=:publicado, publicado_en=:ahora",
            ConditionExpression="#estado=:pendiente",
            ExpressionAttributeNames={"#estado": "estado"},
            ExpressionAttributeValues={
                ":publicado": "PUBLICADO",
                ":pendiente": "PENDIENTE",
                ":ahora": datetime.now(timezone.utc).strftime(FECHA),
            },
        )
    except ClientError:
        # SNS pudo publicar antes de que fallara la marca. El OUTBOX
        # pendiente se reintentara; INBOX evita aplicar efectos dos veces.
        raise
    return "publicado"


def lambda_handler(event, context):
    registros = event.get("Records", [])
    if not isinstance(registros, list):
        raise ValueError("Records debe ser una lista")
    totales = {"procesados": 0, "duplicados": 0}
    for registro in registros:
        try:
            if (registro.get("eventSource") != "aws:sqs"
                    or registro.get("eventSourceARN") != SQS_ARN):
                raise ValueError("Origen SQS no autorizado")
            mensaje = json.loads(registro["body"])
            estado, llave = procesar(mensaje)
            # Tambien se intenta tras duplicado: recupera fallo SNS post-transaccion.
            publicar_outbox(llave)
            totales["procesados" if estado == "finalizado" else "duplicados"] += 1
            print(json.dumps({
                "tipo": "INFO", "resultado": estado,
                "event_id": mensaje["event_id"], "tenant_id": mensaje["tenant_id"],
            }))
        except Exception as exc:
            print(json.dumps({
                "tipo": "ERROR", "error": type(exc).__name__,
                "message_id": registro.get("messageId"),
            }))
            # batchSize=1: fallo completo reintentable, luego DLQ.
            raise
    return totales
