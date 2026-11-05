"""Consumidor manual de SQS Agenda: ParteFinalizado -> visita FINALIZADA.

Copiar en AWS Lambda > Code > lambda_function.py. Por seguridad, NO
conectar el trigger SQS hasta probar la función y revisar su rol.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

AGENDA_TABLE = os.environ["AGENDA_TABLE"]
SQS_AGENDA_ARN = os.environ["SQS_AGENDA_ARN"]
DB = boto3.resource("dynamodb").Table(AGENDA_TABLE)
CLIENT = boto3.client("dynamodb")
SER = TypeSerializer()

TENANTS = {"CLIMALIMA", "FRIOSUR", "TECNINORTE"}
RESULTADOS = {"RESUELTO", "REQUIERE_REVISITA", "NO_ATENDIDO"}
UUID = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
FECHA = "%Y-%m-%dT%H:%M:%SZ"


def av(item):
    return {key: SER.serialize(value) for key, value in item.items()}


def validar_evento(e):
    if not isinstance(e, dict) or not isinstance(e.get("data"), dict):
        raise ValueError("Mensaje SQS: estructura JSON inválida")
    d = e["data"]
    ids = [e.get("event_id"), e.get("aggregate_id"), d.get("parte_id"),
           d.get("visita_id"), d.get("orden_id")]
    if not all(isinstance(x, str) and UUID.fullmatch(x) for x in ids):
        raise ValueError("Mensaje SQS: UUID inválido")
    if (e.get("event_type") != "ParteFinalizado"
            or e.get("tenant_id") not in TENANTS
            or e.get("aggregate_type") != "PARTE"
            or e["aggregate_id"] != d["parte_id"]
            or e.get("correlation_id") != d["visita_id"]
            or type(e.get("schema_version")) is not int
            or e["schema_version"] != 1
            or type(e.get("aggregate_version")) is not int
            or e["aggregate_version"] < 2
            or d.get("resultado") not in RESULTADOS):
        raise ValueError("Mensaje SQS: evento no admitido")
    fecha = e.get("occurred_at")
    if not isinstance(fecha, str):
        raise ValueError("Mensaje SQS: fecha ausente")
    try:
        instante = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Mensaje SQS: fecha inválida") from exc
    if instante.tzinfo is None:
        raise ValueError("Mensaje SQS: fecha sin zona horaria")
    return e


def claves_bloques(visita):
    try:
        inicio = datetime.strptime(visita["inicio"], FECHA).replace(
            tzinfo=timezone.utc
        )
        fin = datetime.strptime(visita["fin"], FECHA).replace(tzinfo=timezone.utc)
        tecnico = visita["tecnico_id"]
        if not isinstance(tecnico, str) or not UUID.fullmatch(tecnico):
            raise ValueError("Técnico inválido")
        duracion = (fin - inicio).total_seconds()
        if (not 1800 <= duracion <= 14400 or duracion % 1800
                or inicio.minute not in (0, 30)
                or fin.minute not in (0, 30)):
            raise ValueError("Horario inconsistente")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Visita tiene bloques inválidos") from exc
    bloques = []
    instante = inicio
    while instante < fin:
        estampado = instante.strftime(FECHA)
        bloques.append(f"BLOQUE#{tecnico}#{estampado}")
        instante += timedelta(minutes=30)
    return bloques


def procesar(e):
    e = validar_evento(e)
    tenant, evento_id = e["tenant_id"], e["event_id"]
    d = e["data"]
    pk = f"TENANT#{tenant}"
    llave_inbox = {"PK": pk, "SK": f"INBOX#{evento_id}"}
    huella = hashlib.sha256(
        json.dumps(e, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    previo = DB.get_item(Key=llave_inbox, ConsistentRead=True).get("Item")
    if previo:
        if previo.get("payload_sha256") != huella:
            raise ValueError("Event ID reutilizado con otro contenido")
        return "duplicado"

    llave_visita = {"PK": pk, "SK": f"VISITA#{d['visita_id']}"}
    visita = DB.get_item(Key=llave_visita, ConsistentRead=True).get("Item")
    if (not visita or visita.get("tenant_id") != tenant
            or visita.get("visita_id") != d["visita_id"]
            or visita.get("orden_id") != d["orden_id"]
            or visita.get("estado") != "EN_ATENCION"):
        raise ValueError("Visita no encontrada o no finalizable")

    bloques = claves_bloques(visita)
    ahora = datetime.now(timezone.utc).isoformat()
    acciones = [
        {"Update": {
            "TableName": AGENDA_TABLE,
            "Key": av(llave_visita),
            "UpdateExpression": (
                "SET #estado = :finalizada, finalizada_en = :ahora "
                "ADD #version :uno"
            ),
            "ConditionExpression": (
                "#estado = :en_atencion AND tenant_id = :tenant "
                "AND visita_id = :visita AND orden_id = :orden "
                "AND tecnico_id = :tecnico AND inicio = :inicio AND fin = :fin"
            ),
            "ExpressionAttributeNames": {
                "#estado": "estado", "#version": "version"
            },
            "ExpressionAttributeValues": av({
                ":finalizada": "FINALIZADA",
                ":en_atencion": "EN_ATENCION",
                ":tenant": tenant,
                ":visita": d["visita_id"],
                ":orden": d["orden_id"],
                ":tecnico": visita["tecnico_id"],
                ":inicio": visita["inicio"],
                ":fin": visita["fin"],
                ":ahora": ahora,
                ":uno": 1,
            }),
        }},
    ]
    for sk in bloques:
        acciones.append({"Delete": {
            "TableName": AGENDA_TABLE,
            "Key": av({"PK": pk, "SK": sk}),
            "ConditionExpression": "visita_id = :visita AND tecnico_id = :tecnico",
            "ExpressionAttributeValues": av({
                ":visita": d["visita_id"], ":tecnico": visita["tecnico_id"],
            }),
        }})
    acciones.append({"Update": {
        "TableName": AGENDA_TABLE,
        "Key": av({"PK": pk, "SK": f"CONTROL_ORDEN#{d['orden_id']}"}),
        "UpdateExpression": "ADD visitas_activas :menos",
        "ConditionExpression": (
            "attribute_exists(PK) AND orden_id = :orden "
            "AND visitas_activas >= :uno"
        ),
        "ExpressionAttributeValues": av({
            ":orden": d["orden_id"], ":menos": -1, ":uno": 1,
        }),
    }})
    acciones.append({"Put": {
        "TableName": AGENDA_TABLE,
        "Item": av({
            **llave_inbox,
            "entity_type": "INBOX",
            "tenant_id": tenant,
            "event_id": evento_id,
            "event_type": "ParteFinalizado",
            "payload_sha256": huella,
            "procesado_en": ahora,
        }),
        "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
    }})

    try:
        CLIENT.transact_write_items(TransactItems=acciones)
    except ClientError:
        # Si hubo una invocación simultánea, podría ser un duplicado ya aplicado.
        previo = DB.get_item(Key=llave_inbox, ConsistentRead=True).get("Item")
        if previo and previo.get("payload_sha256") == huella:
            return "duplicado"
        raise
    return "finalizado"


def lambda_handler(event, context):
    registros = event.get("Records", [])
    if not isinstance(registros, list):
        raise ValueError("Records debe ser una lista")
    contadores = {"procesados": 0, "duplicados": 0}
    for registro in registros:
        try:
            if (registro.get("eventSource") != "aws:sqs"
                    or registro.get("eventSourceARN") != SQS_AGENDA_ARN):
                raise ValueError("Origen SQS no autorizado")
            mensaje = json.loads(registro["body"])
            resultado = procesar(mensaje)
            contadores["procesados" if resultado == "finalizado" else "duplicados"] += 1
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
            # Con trigger SQS de batch size 1, fallar hace que SQS reintente.
            raise
    return contadores
