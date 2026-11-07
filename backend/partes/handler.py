"""MS5 Partes y evidencias: borradores, S3 privado y finalización.

La finalización guarda el estado FINALIZADO y un evento OUTBOX atómicamente.
Se intenta publicar ParteFinalizado en SNS despues de la transaccion; si
falla, el OUTBOX persiste y puede recuperarse sin Streams.
"""
import json
import os
import re
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.config import Config
from botocore.exceptions import ClientError
from json_utils import decimal_default

TABLE_NAME = os.environ["PARTES_TABLE"]
BUCKET_NAME = os.environ["EVIDENCIAS_BUCKET"]
AGENDA_BASE = os.environ["AGENDA_API_BASE"].rstrip("/")
REGION = os.environ.get("AWS_REGION", "us-east-1")
TOPIC_ARN = os.environ.get("EVENTOS_TOPIC_ARN", "").strip()
MAX_IMAGE = 5 * 1024 * 1024
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
TENANTS = {"CLIMALIMA", "FRIOSUR", "TECNINORTE"}
ROLES = {"ADMIN", "COORDINADOR"}
MIME_TO_EXT = {"image/png": ".png", "image/jpeg": ".jpg"}
RESULTADOS = {"PENDIENTE", "RESUELTO", "REQUIERE_REVISITA", "NO_ATENDIDO"}

TABLE = boto3.resource("dynamodb").Table(TABLE_NAME)
DYNAMODB = boto3.client("dynamodb")
SNS = boto3.client("sns")
SER = TypeSerializer()
S3 = boto3.client(
    "s3", region_name=REGION,
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)


def reply(status, data):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(data, ensure_ascii=False, default=decimal_default),
    }


def principal(event):
    claims = (event.get("requestContext") or {}).get("authorizer") or {}
    tenant = claims.get("tenant_id")
    user = claims.get("usuario_id")
    if tenant not in TENANTS or not user:
        return None, reply(401, {"error": "No autorizado"})
    if claims.get("rol") not in ROLES:
        return None, reply(403, {"error": "Operación no permitida"})
    return (tenant, user), None


def bearer(event):
    value = next((
        val for key, val in (event.get("headers") or {}).items()
        if isinstance(key, str) and key.lower() == "authorization"
    ), None)
    if not isinstance(value, str) or not value.lower().startswith("bearer "):
        return None
    return value


def get_visit(visita_id, token):
    req = urllib.request.Request(
        AGENDA_BASE + "/visitas/" + visita_id,
        headers={"Authorization": token, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            if response.status != 200:
                return None, 502
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            return None, exc.code
        return None, 502
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None, 502
    if not isinstance(payload, dict):
        return None, 502
    visita = payload.get("visita")
    if not isinstance(visita, dict):
        return None, 502
    return visita, 200


def path_id(event, name):
    value = (event.get("pathParameters") or {}).get(name, "")
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise ValueError(name + " inválido")
    return value


def json_body(event, fields):
    try:
        data = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("JSON inválido") from exc
    if not isinstance(data, dict) or (set(data) - fields):
        raise ValueError("Campos no permitidos")
    return data


def to_av(value):
    return {k: SER.serialize(v) for k, v in value.items()}


def now():
    return datetime.now(timezone.utc).isoformat()


def public_part(item):
    return {k: item.get(k) for k in (
        "parte_id", "visita_id", "orden_id", "tenant_id", "estado",
        "diagnostico", "tareas", "resultado", "creado_en", "actualizado_en", "version",
        "finalizado_en", "evento_finalizacion_id",
    )}


def public_evidence(item):
    return {k: item.get(k) for k in (
        "evidencia_id", "parte_id", "tenant_id", "content_type", "estado",
        "size_bytes", "creado_en", "confirmado_en",
    ) if k in item}


def get_part(tenant, parte_id):
    return TABLE.get_item(
        Key={"PK": f"TENANT#{tenant}", "SK": f"PARTE#{parte_id}"},
        ConsistentRead=True,
    ).get("Item")


def get_evidence(tenant, parte_id, evidencia_id):
    return TABLE.get_item(
        Key={
            "PK": f"TENANT#{tenant}",
            "SK": f"EVIDENCIA#{parte_id}#{evidencia_id}",
        },
        ConsistentRead=True,
    ).get("Item")


def crear_borrador(event, context):
    actor, error = principal(event)
    if error:
        return error
    try:
        visita_id = path_id(event, "visita_id")
        data = json_body(event, set())
    except ValueError as exc:
        return reply(400, {"error": str(exc)})
    token = bearer(event)
    if not token:
        return reply(401, {"error": "No autorizado"})
    visit, status = get_visit(visita_id, token)
    if status != 200:
        return reply(
            status if status in (401, 403, 404) else 502,
            {"error": "No fue posible verificar la visita"},
        )
    tenant, user = actor
    if visit.get("tenant_id") != tenant or visit.get("visita_id") != visita_id:
        return reply(404, {"error": "Visita no encontrada"})
    if visit.get("estado") not in ("PROGRAMADA", "EN_ATENCION"):
        return reply(409, {"error": "Estado de visita incompatible"})
    orden_id = visit.get("orden_id")
    if not isinstance(orden_id, str) or not UUID_RE.fullmatch(orden_id):
        return reply(502, {"error": "Visita sin orden válida"})

    parte_id = str(uuid.uuid4())
    pk = f"TENANT#{tenant}"
    item = {
        "PK": pk, "SK": f"PARTE#{parte_id}", "entity_type": "PARTE",
        "tenant_id": tenant, "parte_id": parte_id, "visita_id": visita_id,
        "orden_id": orden_id, "estado": "BORRADOR",
        "diagnostico": "", "tareas": [], "resultado": "PENDIENTE",
        "creado_por": user, "creado_en": now(), "actualizado_en": now(),
        "version": 1,
    }
    mark = {
        "PK": pk, "SK": f"VISITA_PARTE#{visita_id}", "entity_type": "VISITA_PARTE",
        "tenant_id": tenant, "visita_id": visita_id, "parte_id": parte_id,
    }
    try:
        DYNAMODB.transact_write_items(TransactItems=[
            {"Put": {
                "TableName": TABLE_NAME, "Item": to_av(item),
                "ConditionExpression": "attribute_not_exists(PK)",
            }},
            {"Put": {
                "TableName": TABLE_NAME, "Item": to_av(mark),
                "ConditionExpression": "attribute_not_exists(PK)",
            }},
        ])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            return reply(409, {"error": "Ya existe un parte para esta visita"})
        raise
    return reply(201, {"parte": public_part(item)})


def consultar(event, context):
    actor, error = principal(event)
    if error:
        return error
    try:
        parte_id = path_id(event, "parte_id")
    except ValueError as exc:
        return reply(400, {"error": str(exc)})
    tenant, _ = actor
    part = get_part(tenant, parte_id)
    if not part:
        return reply(404, {"error": "Parte no encontrado"})
    response = TABLE.query(
        KeyConditionExpression=(
            Key("PK").eq(f"TENANT#{tenant}") &
            Key("SK").begins_with(f"EVIDENCIA#{parte_id}#")
        ),
        ConsistentRead=True,
        Limit=20,
    )
    return reply(200, {
        "parte": public_part(part),
        "evidencias": [public_evidence(e) for e in response.get("Items", [])],
    })


def actualizar(event, context):
    actor, error = principal(event)
    if error:
        return error
    try:
        parte_id = path_id(event, "parte_id")
        data = json_body(event, {"diagnostico", "tareas", "resultado", "version"})
        if set(data) != {"diagnostico", "tareas", "resultado", "version"}:
            raise ValueError("Se requieren diagnostico, tareas, resultado y version")
        diag = data["diagnostico"]
        tareas = data["tareas"]
        resultado = data["resultado"]
        version = data["version"]
        if not isinstance(diag, str) or len(diag.strip()) > 1000:
            raise ValueError("diagnostico inválido")
        if (not isinstance(tareas, list) or len(tareas) > 20 or
                any(not isinstance(t, str) or not 1 <= len(t.strip()) <= 200 for t in tareas)):
            raise ValueError("tareas inválidas")
        if not isinstance(resultado, str) or resultado not in RESULTADOS:
            raise ValueError("resultado inválido")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("version inválida")
    except (ValueError, TypeError) as exc:
        return reply(400, {"error": str(exc)})

    tenant, _ = actor
    if not get_part(tenant, parte_id):
        return reply(404, {"error": "Parte no encontrado"})
    try:
        result = TABLE.update_item(
            Key={"PK": f"TENANT#{tenant}", "SK": f"PARTE#{parte_id}"},
            UpdateExpression=(
                "SET diagnostico = :diag, tareas = :tareas, resultado = :resultado, "
                "actualizado_en = :when, #version = :newversion"
            ),
            ConditionExpression="#estado = :borrador AND #version = :expected",
            ExpressionAttributeNames={"#estado": "estado", "#version": "version"},
            ExpressionAttributeValues={
                ":diag": diag.strip(),
                ":tareas": [t.strip() for t in tareas],
                ":resultado": resultado,
                ":when": now(),
                ":newversion": version + 1,
                ":borrador": "BORRADOR",
                ":expected": version,
            },
            ReturnValues="ALL_NEW",
        )
    except TABLE.meta.client.exceptions.ConditionalCheckFailedException:
        return reply(409, {"error": "Versión desactualizada o parte no editable"})
    return reply(200, {"parte": public_part(result["Attributes"])})


def pedir_carga(event, context):
    actor, error = principal(event)
    if error:
        return error
    try:
        parte_id = path_id(event, "parte_id")
        data = json_body(event, {"content_type"})
        content_type = data.get("content_type")
        if content_type not in MIME_TO_EXT:
            raise ValueError("Se admiten image/jpeg e image/png")
    except ValueError as exc:
        return reply(400, {"error": str(exc)})
    tenant, _ = actor
    part = get_part(tenant, parte_id)
    if not part:
        return reply(404, {"error": "Parte no encontrado"})
    if part.get("estado") != "BORRADOR":
        return reply(409, {"error": "El parte no admite evidencias"})

    evidencia_id = str(uuid.uuid4())
    object_key = (
        f"tenants/{tenant}/partes/{parte_id}/{evidencia_id}"
        + MIME_TO_EXT[content_type]
    )
    item = {
        "PK": f"TENANT#{tenant}",
        "SK": f"EVIDENCIA#{parte_id}#{evidencia_id}",
        "entity_type": "EVIDENCIA",
        "tenant_id": tenant,
        "parte_id": parte_id,
        "evidencia_id": evidencia_id,
        "estado": "PENDIENTE",
        "content_type": content_type,
        "object_key": object_key,
        "creado_en": now(),
    }
    try:
        form = S3.generate_presigned_post(
            Bucket=BUCKET_NAME,
            Key=object_key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, MAX_IMAGE],
            ],
            ExpiresIn=300,
        )
        TABLE.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except ClientError as exc:
        print("Error creando autorización de S3:", exc.response.get("Error", {}).get("Code"))
        return reply(500, {"error": "No se pudo preparar la carga"})
    return reply(201, {
        "evidencia": public_evidence(item),
        "upload": {"url": form["url"], "fields": form["fields"], "expira_en_segundos": 300},
        "tamano_maximo_bytes": MAX_IMAGE,
    })


def confirmar_carga(event, context):
    actor, error = principal(event)
    if error:
        return error
    try:
        parte_id = path_id(event, "parte_id")
        evidencia_id = path_id(event, "evidencia_id")
    except ValueError as exc:
        return reply(400, {"error": str(exc)})
    tenant, _ = actor
    part = get_part(tenant, parte_id)
    if not part:
        return reply(404, {"error": "Parte no encontrado"})
    evidence = get_evidence(tenant, parte_id, evidencia_id)
    if not evidence:
        return reply(404, {"error": "Evidencia no encontrada"})
    if evidence.get("estado") == "CONFIRMADA":
        return reply(200, {"evidencia": public_evidence(evidence)})
    if evidence.get("estado") != "PENDIENTE" or part.get("estado") != "BORRADOR":
        return reply(409, {"error": "Evidencia no confirmable"})
    try:
        head = S3.head_object(Bucket=BUCKET_NAME, Key=evidence["object_key"])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("ResponseMetadata", {}).get("HTTPStatusCode") in (403, 404):
            return reply(409, {"error": "Archivo aún no disponible o sin acceso"})
        raise
    size = head.get("ContentLength", 0)
    if not 1 <= size <= MAX_IMAGE or head.get("ContentType") != evidence["content_type"]:
        return reply(422, {"error": "Tamaño o tipo de archivo inválido"})
    try:
        result = TABLE.update_item(
            Key={"PK": f"TENANT#{tenant}", "SK": f"EVIDENCIA#{parte_id}#{evidencia_id}"},
            UpdateExpression=(
                "SET #estado = :confirmada, size_bytes = :size, confirmado_en = :now"
            ),
            ConditionExpression="#estado = :pendiente",
            ExpressionAttributeNames={"#estado": "estado"},
            ExpressionAttributeValues={
                ":confirmada": "CONFIRMADA",
                ":pendiente": "PENDIENTE",
                ":size": size,
                ":now": now(),
            },
            ReturnValues="ALL_NEW",
        )
    except TABLE.meta.client.exceptions.ConditionalCheckFailedException:
        return reply(409, {"error": "Evidencia cambiada por otra solicitud"})
    return reply(200, {"evidencia": public_evidence(result["Attributes"])})



def existe_evidencia_confirmada(tenant, parte_id):
    """Busca al menos una evidencia confirmada, sin asumir una sola página DynamoDB."""
    parametros = {
        "KeyConditionExpression": (
            Key("PK").eq(f"TENANT#{tenant}") &
            Key("SK").begins_with(f"EVIDENCIA#{parte_id}#")
        ),
        "ConsistentRead": True,
        "Limit": 100,
    }
    paginas = 0
    while True:
        respuesta = TABLE.query(**parametros)
        if any(
            e.get("estado") == "CONFIRMADA"
            and e.get("tenant_id") == tenant
            and e.get("parte_id") == parte_id
            for e in respuesta.get("Items", [])
        ):
            return True
        ultimo = respuesta.get("LastEvaluatedKey")
        if not ultimo:
            return False
        paginas += 1
        if paginas > 100:
            # Evita finalizar si hay una cantidad de evidencias anormalmente alta.
            raise ValueError("Demasiadas evidencias para validar el parte")
        parametros["ExclusiveStartKey"] = ultimo


def publicar_outbox(outbox):
    """Publica un evento ya persistido; una falla nunca borra su OUTBOX.

    SNS puede aceptar el mensaje y fallar la marca PUBLICADO. Ese caso produce
    republicacion posterior, segura porque cada consumidor usa INBOX/event_id.
    """
    if outbox.get("estado") == "PUBLICADO":
        return "PUBLICADO"
    if not TOPIC_ARN:
        return "PENDIENTE_PUBLICACION"
    if (outbox.get("estado") != "PENDIENTE"
            or outbox.get("entity_type") != "OUTBOX"
            or outbox.get("tenant_id") not in TENANTS
            or not isinstance(outbox.get("payload"), dict)
            or outbox["payload"].get("event_id") != outbox.get("event_id")
            or outbox["payload"].get("tenant_id") != outbox.get("tenant_id")
            or outbox["payload"].get("event_type") != "ParteFinalizado"):
        print(json.dumps({"tipo": "ERROR", "error": "OutboxInvalido"}))
        return "PENDIENTE_PUBLICACION"
    try:
        SNS.publish(
            TopicArn=TOPIC_ARN,
            Message=json.dumps(outbox["payload"], ensure_ascii=False, separators=(",", ":"),
                               default=decimal_default),
        )
    except Exception as exc:
        print(json.dumps({
            "tipo": "ERROR", "operacion": "sns_publish",
            "error": type(exc).__name__, "event_id": outbox["event_id"],
        }))
        return "PENDIENTE_PUBLICACION"

    try:
        TABLE.update_item(
            Key={"PK": outbox["PK"], "SK": outbox["SK"]},
            UpdateExpression="SET #estado=:publicado, publicado_en=:ahora",
            ConditionExpression="#estado=:pendiente",
            ExpressionAttributeNames={"#estado": "estado"},
            ExpressionAttributeValues={
                ":publicado": "PUBLICADO", ":pendiente": "PENDIENTE",
                ":ahora": now(),
            },
        )
    except Exception as exc:
        print(json.dumps({
            "tipo": "ERROR", "operacion": "marcar_outbox",
            "error": type(exc).__name__, "event_id": outbox["event_id"],
        }))
        # El mensaje pudo publicarse: OUTBOX queda recuperable.
        return "PENDIENTE_PUBLICACION"
    return "PUBLICADO"


def finalizar(event, context):
    """BORRADOR -> FINALIZADO, con evento OUTBOX en la misma transacción.

    Solo se finaliza una visita EN_ATENCION del mismo tenant y orden.
    Publicacion directa SNS despues del commit; OUTBOX recuperable ante falla.
    """
    actor, error = principal(event)
    if error:
        return error
    try:
        parte_id = path_id(event, "parte_id")
        datos = json_body(event, {"version"})
        if set(datos) != {"version"}:
            raise ValueError("Se requiere la versión actual del parte")
        version = datos["version"]
        if type(version) is not int or not 1 <= version <= 2_000_000_000:
            raise ValueError("version debe ser un entero positivo")
    except ValueError as exc:
        return reply(400, {"error": str(exc)})

    tenant, usuario = actor
    part = get_part(tenant, parte_id)
    if not part:
        return reply(404, {"error": "Parte no encontrado"})

    # Una nueva petición tras un éxito no debe producir un segundo OUTBOX.
    if part.get("estado") == "FINALIZADO":
        estado = "PENDIENTE_PUBLICACION"
        evento_previo_id = part.get("evento_finalizacion_id")
        if isinstance(evento_previo_id, str) and UUID_RE.fullmatch(evento_previo_id):
            pendiente = TABLE.get_item(
                Key={"PK": f"TENANT#{tenant}", "SK": f"OUTBOX#{evento_previo_id}"},
                ConsistentRead=True,
            ).get("Item")
            if pendiente:
                estado = publicar_outbox(pendiente)
        return reply(200, {
            "parte": public_part(part),
            "sin_cambios": True,
            "evento": {
                "event_id": evento_previo_id,
                "event_type": "ParteFinalizado",
                "estado": estado,
            },
        })
    if part.get("estado") != "BORRADOR":
        return reply(409, {"error": "Solo se puede finalizar un borrador"})
    try:
        version_actual = part["version"]
        if isinstance(version_actual, bool) or int(version_actual) != version:
            return reply(409, {"error": "Versión desactualizada"})
    except (KeyError, ValueError, TypeError):
        return reply(409, {"error": "Versión del parte inconsistente"})

    diagnostico = part.get("diagnostico", "")
    tareas = part.get("tareas")
    resultado = part.get("resultado")
    if not isinstance(diagnostico, str) or not diagnostico.strip():
        return reply(422, {"error": "Se requiere un diagnóstico antes de finalizar"})
    if (not isinstance(tareas, list) or not tareas
            or any(not isinstance(t, str) or not t.strip() for t in tareas)):
        return reply(422, {"error": "Se requiere al menos una tarea registrada"})
    if resultado not in (RESULTADOS - {"PENDIENTE"}):
        return reply(422, {"error": "Indica un resultado antes de finalizar"})

    token = bearer(event)
    if not token:
        return reply(401, {"error": "No autorizado"})
    visita_id = part.get("visita_id")
    orden_id = part.get("orden_id")
    if (not isinstance(visita_id, str) or not UUID_RE.fullmatch(visita_id)
            or not isinstance(orden_id, str) or not UUID_RE.fullmatch(orden_id)):
        return reply(409, {"error": "Identificadores del parte inconsistentes"})
    visit, status = get_visit(visita_id, token)
    if status != 200:
        return reply(
            status if status in (401, 403, 404) else 502,
            {"error": "No fue posible validar la visita de MS4"},
        )
    if (visit.get("tenant_id") != tenant or visit.get("visita_id") != visita_id
            or visit.get("orden_id") != orden_id):
        return reply(404, {"error": "Visita no encontrada"})
    if visit.get("estado") != "EN_ATENCION":
        return reply(409, {"error": "La visita debe estar EN_ATENCION"})

    try:
        if not existe_evidencia_confirmada(tenant, parte_id):
            return reply(422, {"error": "Confirma al menos una evidencia antes de finalizar"})
    except (ClientError, ValueError):
        return reply(503, {"error": "No fue posible verificar las evidencias"})

    evento_id = str(uuid.uuid4())
    fecha = now()
    nueva_version = version + 1
    evento = {
        "event_id": evento_id,
        "event_type": "ParteFinalizado",
        "schema_version": 1,
        "tenant_id": tenant,
        "aggregate_type": "PARTE",
        "aggregate_id": parte_id,
        "aggregate_version": nueva_version,
        "occurred_at": fecha,
        "correlation_id": visita_id,
        "data": {
            "visita_id": visita_id,
            "orden_id": orden_id,
            "parte_id": parte_id,
            "resultado": resultado,
        },
    }
    outbox = {
        "PK": f"TENANT#{tenant}",
        "SK": f"OUTBOX#{evento_id}",
        "entity_type": "OUTBOX",
        "tenant_id": tenant,
        "event_id": evento_id,
        "event_type": "ParteFinalizado",
        "payload": evento,
        "estado": "PENDIENTE",
        "creado_en": fecha,
    }

    try:
        DYNAMODB.transact_write_items(TransactItems=[
            {"Update": {
                "TableName": TABLE_NAME,
                "Key": to_av({
                    "PK": f"TENANT#{tenant}", "SK": f"PARTE#{parte_id}",
                }),
                "UpdateExpression": (
                    "SET #estado = :finalizado, #version = :nueva_version, "
                    "finalizado_en = :fecha, actualizado_en = :fecha, "
                    "evento_finalizacion_id = :evento_id, finalizado_por = :usuario"
                ),
                "ConditionExpression": (
                    "#estado = :borrador AND #version = :version"
                ),
                "ExpressionAttributeNames": {
                    "#estado": "estado", "#version": "version",
                },
                "ExpressionAttributeValues": to_av({
                    ":finalizado": "FINALIZADO",
                    ":borrador": "BORRADOR",
                    ":version": version,
                    ":nueva_version": nueva_version,
                    ":fecha": fecha,
                    ":evento_id": evento_id,
                    ":usuario": usuario,
                }),
            }},
            {"Put": {
                "TableName": TABLE_NAME,
                "Item": to_av(outbox),
                "ConditionExpression": "attribute_not_exists(PK)",
            }},
        ])
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("TransactionCanceledException", "ConditionalCheckFailedException"):
            return reply(409, {"error": "El parte cambió durante la finalización; consulta de nuevo"})
        print("Error al finalizar parte con OUTBOX:", code)
        return reply(500, {"error": "No se pudo finalizar el parte"})

    estado_publicacion = publicar_outbox(outbox)

    cambiado = dict(part)
    cambiado.update({
        "estado": "FINALIZADO",
        "version": nueva_version,
        "finalizado_en": fecha,
        "actualizado_en": fecha,
        "evento_finalizacion_id": evento_id,
    })
    return reply(200, {
        "parte": public_part(cambiado),
        "sin_cambios": False,
        "evento": {
            "event_id": evento_id,
            "event_type": "ParteFinalizado",
            "estado": estado_publicacion,
        },
    })

def enlace_lectura(event, context):
    actor, error = principal(event)
    if error:
        return error
    try:
        parte_id = path_id(event, "parte_id")
        evidencia_id = path_id(event, "evidencia_id")
    except ValueError as exc:
        return reply(400, {"error": str(exc)})
    tenant, _ = actor
    if not get_part(tenant, parte_id):
        return reply(404, {"error": "Parte no encontrado"})
    evidence = get_evidence(tenant, parte_id, evidencia_id)
    if not evidence or evidence.get("estado") != "CONFIRMADA":
        return reply(404, {"error": "Evidencia no confirmada"})
    url = S3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": evidence["object_key"]},
        ExpiresIn=120,
    )
    return reply(200, {"url": url, "expira_en_segundos": 120})


def buscar_por_visita(event, context):
    """Recupera el único borrador existente de una visita (evita duplicados)."""
    actor, error = principal(event)
    if error:
        return error
    try:
        visita_id = path_id(event, "visita_id")
    except ValueError as exc:
        return reply(400, {"error": str(exc)})
    tenant, _ = actor
    marker = TABLE.get_item(
        Key={"PK": f"TENANT#{tenant}", "SK": f"VISITA_PARTE#{visita_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not marker:
        return reply(404, {"error": "La visita aún no tiene parte"})
    parte_id = marker.get("parte_id")
    if not isinstance(parte_id, str) or not UUID_RE.fullmatch(parte_id):
        return reply(500, {"error": "Parte inconsistente"})
    part = get_part(tenant, parte_id)
    if not part:
        return reply(500, {"error": "Parte inconsistente"})
    return reply(200, {"parte": public_part(part)})
