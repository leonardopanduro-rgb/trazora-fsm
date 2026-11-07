"""MS3 Órdenes de trabajo: primera API REST, aislada por tenant.

La creación verifica cliente_id a través de MS1 Clientes usando el mismo
token de sesión, sin leer ni modificar la tabla de MS1 directamente.
"""
import base64
import binascii
import json
import os
import re
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE = boto3.resource("dynamodb").Table(os.environ["ORDENES_TABLE"])
CLIENTES_API_BASE = os.environ["CLIENTES_API_BASE"].rstrip("/")
TENANTS = frozenset(("CLIMALIMA", "FRIOSUR", "TECNINORTE"))
ROLES = frozenset(("ADMIN", "COORDINADOR"))
SERVICIOS = frozenset(("INSTALACION", "MANTENIMIENTO", "REPARACION"))
PRIORIDADES = frozenset(("BAJA", "MEDIA", "ALTA"))
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def responder(status, contenido):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(contenido, ensure_ascii=False),
    }


def identidad(event):
    claims = (event.get("requestContext") or {}).get("authorizer") or {}
    tenant = claims.get("tenant_id")
    usuario_id = claims.get("usuario_id")
    rol = claims.get("rol")
    if tenant not in TENANTS or not usuario_id:
        return None, responder(401, {"error": "No autorizado"})
    if rol not in ROLES:
        return None, responder(403, {"error": "Rol sin permisos"})
    return {"tenant_id": tenant, "usuario_id": usuario_id}, None


def token_original(event):
    headers = event.get("headers") or {}
    value = next((v for k, v in headers.items()
                  if isinstance(k, str) and k.lower() == "authorization"), None)
    if not isinstance(value, str) or not value.lower().startswith("bearer "):
        return None
    return value


def verificar_cliente(tenant, cliente_id, event):
    """Retorna (True, None) o (False, respuesta HTTP)."""
    bearer = token_original(event)
    if not bearer:
        return False, responder(401, {"error": "No autorizado"})
    req = urllib.request.Request(
        CLIENTES_API_BASE + "/clientes/" + cliente_id,
        headers={"Authorization": bearer, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                return False, responder(502, {"error": "No se pudo validar el cliente"})
            datos = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, responder(404, {"error": "Cliente no encontrado en esta empresa"})
        if exc.code in (401, 403):
            return False, responder(exc.code, {"error": "No autorizado para validar cliente"})
        return False, responder(502, {"error": "Servicio Clientes no disponible"})
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False, responder(502, {"error": "Servicio Clientes no disponible"})

    cliente = datos.get("cliente", {}) if isinstance(datos, dict) else {}
    if (cliente.get("cliente_id") != cliente_id or
            cliente.get("tenant_id") != tenant or cliente.get("activo") is not True):
        return False, responder(422, {"error": "Cliente inválido o inactivo"})
    return True, None


def mostrar(item):
    datos = {key: item.get(key) for key in (
        "orden_id", "tenant_id", "cliente_id", "tipo_servicio",
        "descripcion", "prioridad", "estado", "creada_en", "creada_por",
    )}
    for key in ("ultimo_resultado", "ultima_visita_id", "ultimo_parte_id",
                "requiere_revisita", "actualizado_en"):
        if key in item:
            datos[key] = item[key]
    return datos


def crear(event, context):
    actor, error = identidad(event)
    if error:
        return error
    try:
        datos = json.loads(event.get("body") or "{}")
        if not isinstance(datos, dict) or set(datos) - {
            "cliente_id", "tipo_servicio", "descripcion", "prioridad"
        }:
            raise ValueError("Campos no permitidos")
        cliente_id = datos.get("cliente_id")
        if not isinstance(cliente_id, str) or not UUID_RE.fullmatch(cliente_id):
            raise ValueError("cliente_id inválido")
        tipo_servicio = datos.get("tipo_servicio")
        if tipo_servicio not in SERVICIOS:
            raise ValueError("tipo_servicio debe ser INSTALACION, MANTENIMIENTO o REPARACION")
        descripcion = datos.get("descripcion")
        if not isinstance(descripcion, str) or not 10 <= len(descripcion.strip()) <= 500:
            raise ValueError("descripcion debe tener entre 10 y 500 caracteres")
        prioridad = datos.get("prioridad", "MEDIA")
        if prioridad not in PRIORIDADES:
            raise ValueError("prioridad inválida")
    except (ValueError, TypeError) as exc:
        return responder(400, {"error": str(exc)})

    tenant = actor["tenant_id"]
    valida, error = verificar_cliente(tenant, cliente_id, event)
    if not valida:
        return error

    orden_id = str(uuid.uuid4())
    item = {
        "PK": f"TENANT#{tenant}",
        "SK": f"ORDEN#{orden_id}",
        "entity_type": "ORDEN",
        "orden_id": orden_id,
        "tenant_id": tenant,
        "cliente_id": cliente_id,
        "tipo_servicio": tipo_servicio,
        "descripcion": descripcion.strip(),
        "prioridad": prioridad,
        "estado": "ABIERTA",
        "creada_por": actor["usuario_id"],
        "creada_en": datetime.now(timezone.utc).isoformat(),
    }
    TABLE.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
    )
    return responder(201, {"orden": mostrar(item)})


def cursor_sk(raw):
    if not isinstance(raw, str) or not 1 <= len(raw) <= 128:
        raise ValueError("Cursor inválido")
    try:
        sk = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("ascii")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise ValueError("Cursor inválido")
    if not sk.startswith("ORDEN#") or not UUID_RE.fullmatch(sk[6:]):
        raise ValueError("Cursor inválido")
    return sk


def listar(event, context):
    actor, error = identidad(event)
    if error:
        return error
    params = event.get("queryStringParameters") or {}
    try:
        limit = int(params.get("limit", "20"))
        if not 1 <= limit <= 50:
            raise ValueError()
    except (TypeError, ValueError):
        return responder(400, {"error": "limit debe estar entre 1 y 50"})

    pk = f"TENANT#{actor['tenant_id']}"
    args = {
        "KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with("ORDEN#"),
        "Limit": limit,
        "ConsistentRead": True,
    }
    if params.get("cursor"):
        try:
            args["ExclusiveStartKey"] = {"PK": pk, "SK": cursor_sk(params["cursor"])}
        except ValueError:
            return responder(400, {"error": "Cursor inválido"})
    data = TABLE.query(**args)
    last = data.get("LastEvaluatedKey")
    next_cursor = None
    if last:
        next_cursor = base64.urlsafe_b64encode(last["SK"].encode("ascii")).decode("ascii").rstrip("=")
    return responder(200, {
        "ordenes": [mostrar(o) for o in data.get("Items", [])],
        "next_cursor": next_cursor,
    })


def buscar(event, context):
    actor, error = identidad(event)
    if error:
        return error
    orden_id = (event.get("pathParameters") or {}).get("orden_id", "")
    if not isinstance(orden_id, str) or not UUID_RE.fullmatch(orden_id):
        return responder(400, {"error": "orden_id inválido"})
    item = TABLE.get_item(
        Key={"PK": f"TENANT#{actor['tenant_id']}", "SK": f"ORDEN#{orden_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not item:
        return responder(404, {"error": "Orden no encontrada"})
    return responder(200, {"orden": mostrar(item)})

def historial(event, context):
    """Historial de eventos de la orden dentro del tenant autenticado."""
    actor, error = identidad(event)
    if error:
        return error
    orden_id = (event.get("pathParameters") or {}).get("orden_id", "")
    if not isinstance(orden_id, str) or not UUID_RE.fullmatch(orden_id):
        return responder(400, {"error": "orden_id invalido"})
    params = event.get("queryStringParameters") or {}
    try:
        limite = int(params.get("limit", "20"))
        if not 1 <= limite <= 50:
            raise ValueError()
    except (TypeError, ValueError):
        return responder(400, {"error": "limit debe estar entre 1 y 50"})
    pk = "TENANT#" + actor["tenant_id"]
    existe = TABLE.get_item(
        Key={"PK": pk, "SK": "ORDEN#" + orden_id},
        ConsistentRead=True,
    ).get("Item")
    if not existe or existe.get("tenant_id") != actor["tenant_id"]:
        return responder(404, {"error": "Orden no encontrada"})
    prefijo = f"HISTORIAL#{orden_id}#"
    consulta = {
        "KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with(prefijo),
        "ConsistentRead": True, "Limit": limite,
    }
    if params.get("cursor"):
        try:
            raw = params["cursor"]
            if not isinstance(raw, str) or not 1 <= len(raw) <= 256:
                raise ValueError()
            sk = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("ascii")
            if not sk.startswith(prefijo) or not UUID_RE.fullmatch(sk[len(prefijo):]):
                raise ValueError()
            consulta["ExclusiveStartKey"] = {"PK": pk, "SK": sk}
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return responder(400, {"error": "Cursor invalido"})
    registros = TABLE.query(**consulta)
    ultimo = registros.get("LastEvaluatedKey")
    next_cursor = None
    if ultimo:
        next_cursor = base64.urlsafe_b64encode(
            ultimo["SK"].encode("ascii")
        ).decode("ascii").rstrip("=")
    campos = ("event_id", "event_type", "visita_id", "parte_id", "resultado",
              "ocurrido_en", "procesado_en", "obsoleto", "estado_anterior")
    return responder(200, {
        "orden_id": orden_id,
        "historial": [
            {k: item.get(k) for k in campos if k in item}
            for item in registros.get("Items", [])
        ],
        "next_cursor": next_cursor,
    })
