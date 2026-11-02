"""MS1 Clientes: crear, listar y consultar con aislamiento multi-tenant."""
import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE = boto3.resource("dynamodb").Table(os.environ["CLIENTES_TABLE"])
TENANTS = {"CLIMALIMA", "FRIOSUR", "TECNINORTE"}
ROLES = {"ADMIN", "COORDINADOR"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def reply(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }


def tenant_from_authorizer(event):
    context = (event.get("requestContext") or {}).get("authorizer") or {}
    tenant = context.get("tenant_id")
    if tenant not in TENANTS or not context.get("usuario_id"):
        return None, reply(401, {"error": "No autorizado"})
    if context.get("rol") not in ROLES:
        return None, reply(403, {"error": "Operación no permitida para este rol"})
    return tenant, None


def text_value(value, name, length, required=False):
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(name + " debe ser texto")
    value = value.strip()
    if len(value) > length or (required and not value):
        raise ValueError(name + " tiene longitud inválida")
    return value


def public(item):
    return {key: item.get(key) for key in
            ("cliente_id", "tenant_id", "nombre", "correo", "telefono", "activo", "creado_en")}


def crear(event, context):
    tenant, error = tenant_from_authorizer(event)
    if error:
        return error
    try:
        data = json.loads(event.get("body") or "{}")
        if not isinstance(data, dict) or set(data) - {"nombre", "correo", "telefono"}:
            raise ValueError("Campos no permitidos")
        nombre = text_value(data.get("nombre"), "nombre", 160, required=True)
        correo = text_value(data.get("correo"), "correo", 254).lower()
        telefono = text_value(data.get("telefono"), "telefono", 40)
        if correo and ("@" not in correo or " " in correo):
            raise ValueError("Correo inválido")
    except (ValueError, TypeError) as exc:
        return reply(400, {"error": str(exc)})

    cliente_id = str(uuid.uuid4())
    item = {
        "PK": f"TENANT#{tenant}", "SK": f"CLIENTE#{cliente_id}",
        "entity_type": "CLIENTE", "tenant_id": tenant,
        "cliente_id": cliente_id, "nombre": nombre, "correo": correo,
        "telefono": telefono, "activo": True,
        "creado_en": datetime.now(timezone.utc).isoformat(),
    }
    TABLE.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
    )
    return reply(201, {"cliente": public(item)})


def decode_cursor(raw):
    if not isinstance(raw, str) or len(raw) > 128:
        raise ValueError("Cursor inválido")
    try:
        sk = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        raise ValueError("Cursor inválido")
    if not sk.startswith("CLIENTE#") or not ID_PATTERN.fullmatch(sk[8:]):
        raise ValueError("Cursor inválido")
    return sk


def listar(event, context):
    tenant, error = tenant_from_authorizer(event)
    if error:
        return error
    query = event.get("queryStringParameters") or {}
    try:
        limit = int(query.get("limit", "20"))
        if not 1 <= limit <= 50:
            raise ValueError()
    except (TypeError, ValueError):
        return reply(400, {"error": "limit debe estar entre 1 y 50"})

    pk = f"TENANT#{tenant}"
    params = {
        "KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with("CLIENTE#"),
        "Limit": limit,
        "ConsistentRead": True,
    }
    if query.get("cursor"):
        try:
            params["ExclusiveStartKey"] = {"PK": pk, "SK": decode_cursor(query["cursor"])}
        except ValueError:
            return reply(400, {"error": "Cursor inválido"})
    result = TABLE.query(**params)
    next_cursor = None
    if result.get("LastEvaluatedKey"):
        sk = result["LastEvaluatedKey"]["SK"]
        next_cursor = base64.urlsafe_b64encode(sk.encode("ascii")).decode("ascii").rstrip("=")
    return reply(200, {
        "clientes": [public(item) for item in result.get("Items", [])],
        "next_cursor": next_cursor,
    })


def buscar(event, context):
    tenant, error = tenant_from_authorizer(event)
    if error:
        return error
    cliente_id = (event.get("pathParameters") or {}).get("cliente_id", "")
    if not isinstance(cliente_id, str) or not ID_PATTERN.fullmatch(cliente_id):
        return reply(400, {"error": "cliente_id inválido"})
    item = TABLE.get_item(
        Key={"PK": f"TENANT#{tenant}", "SK": f"CLIENTE#{cliente_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not item:
        return reply(404, {"error": "Cliente no encontrado"})
    return reply(200, {"cliente": public(item)})
