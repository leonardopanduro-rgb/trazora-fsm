"""MS2 Técnicos: perfiles y jornadas de trabajo por tenant.

Primera versión académica: ADMIN/COORDINADOR; sin gestión de ausencias ni reservas.
El tenant llega únicamente del autorizador Lambda configurado en API Gateway.
"""
import base64
import binascii
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE = boto3.resource("dynamodb").Table(os.environ["TECNICOS_TABLE"])
TENANTS = frozenset(("CLIMALIMA", "FRIOSUR", "TECNINORTE"))
WRITERS = frozenset(("ADMIN", "COORDINADOR"))
ESPECIALIDADES = frozenset(("INSTALACION", "MANTENIMIENTO", "REPARACION"))
ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):(00|30)$")


def respuesta(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }


def autenticado(event):
    contexto = (event.get("requestContext") or {}).get("authorizer") or {}
    tenant = contexto.get("tenant_id")
    if tenant not in TENANTS or not contexto.get("usuario_id"):
        return None, respuesta(401, {"error": "No autorizado"})
    if contexto.get("rol") not in WRITERS:
        return None, respuesta(403, {"error": "Rol sin permisos para esta operación"})
    return tenant, None


def id_param(event):
    tecnico_id = (event.get("pathParameters") or {}).get("tecnico_id", "")
    if not isinstance(tecnico_id, str) or not ID_RE.fullmatch(tecnico_id):
        raise ValueError("tecnico_id inválido")
    return tecnico_id


def datos_json(event, campos):
    try:
        datos = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("JSON inválido") from exc
    if not isinstance(datos, dict) or (set(datos) - campos):
        raise ValueError("Campos no permitidos")
    return datos


def publico_tecnico(item):
    return {k: item.get(k) for k in
            ("tecnico_id", "tenant_id", "nombre", "especialidades", "activo", "creado_en")}


def publico_jornada(item):
    return {k: item.get(k) for k in
            ("tecnico_id", "tenant_id", "fecha", "zona_horaria", "intervalos", "actualizado_en")}


def tecnico_de(tenant, tecnico_id):
    return TABLE.get_item(
        Key={"PK": f"TENANT#{tenant}", "SK": f"TECNICO#{tecnico_id}"},
        ConsistentRead=True,
    ).get("Item")


def crear(event, context):
    tenant, error = autenticado(event)
    if error:
        return error
    try:
        datos = datos_json(event, {"nombre", "especialidades"})
        nombre = datos.get("nombre")
        especialidades = datos.get("especialidades")
        if not isinstance(nombre, str) or not 3 <= len(nombre.strip()) <= 120:
            raise ValueError("nombre debe tener entre 3 y 120 caracteres")
        if (not isinstance(especialidades, list) or
                not 1 <= len(especialidades) <= 3 or
                any(not isinstance(e, str) or e not in ESPECIALIDADES for e in especialidades) or
                len(set(especialidades)) != len(especialidades)):
            raise ValueError("especialidades inválidas o duplicadas")
    except ValueError as exc:
        return respuesta(400, {"error": str(exc)})

    tecnico_id = str(uuid.uuid4())
    item = {
        "PK": f"TENANT#{tenant}", "SK": f"TECNICO#{tecnico_id}",
        "entity_type": "TECNICO",
        "tenant_id": tenant,
        "tecnico_id": tecnico_id,
        "nombre": nombre.strip(),
        "especialidades": especialidades,
        "activo": True,
        "creado_en": datetime.now(timezone.utc).isoformat(),
    }
    TABLE.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
    )
    return respuesta(201, {"tecnico": publico_tecnico(item)})


def cursor_sk(cursor):
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 128:
        raise ValueError("Cursor inválido")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        sk = raw.decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ValueError("Cursor inválido")
    if not sk.startswith("TECNICO#") or not ID_RE.fullmatch(sk[8:]):
        raise ValueError("Cursor inválido")
    return sk


def listar(event, context):
    tenant, error = autenticado(event)
    if error:
        return error
    query = event.get("queryStringParameters") or {}
    try:
        limit = int(query.get("limit", "20"))
        if not 1 <= limit <= 50:
            raise ValueError()
    except (ValueError, TypeError):
        return respuesta(400, {"error": "limit debe estar entre 1 y 50"})

    pk = f"TENANT#{tenant}"
    parametros = {
        "KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with("TECNICO#"),
        "ConsistentRead": True,
        "Limit": limit,
    }
    if query.get("cursor"):
        try:
            parametros["ExclusiveStartKey"] = {"PK": pk, "SK": cursor_sk(query["cursor"])}
        except ValueError:
            return respuesta(400, {"error": "Cursor inválido"})

    resultado = TABLE.query(**parametros)
    ultimo = resultado.get("LastEvaluatedKey")
    siguiente = None
    if ultimo:
        siguiente = base64.urlsafe_b64encode(ultimo["SK"].encode("ascii")).decode("ascii").rstrip("=")
    return respuesta(200, {
        "tecnicos": [publico_tecnico(t) for t in resultado.get("Items", [])],
        "next_cursor": siguiente,
    })


def buscar(event, context):
    tenant, error = autenticado(event)
    if error:
        return error
    try:
        tecnico_id = id_param(event)
    except ValueError as exc:
        return respuesta(400, {"error": str(exc)})
    tecnico = tecnico_de(tenant, tecnico_id)
    if not tecnico:
        return respuesta(404, {"error": "Técnico no encontrado"})
    return respuesta(200, {"tecnico": publico_tecnico(tecnico)})


def fecha_iso(valor):
    if not isinstance(valor, str) or len(valor) != 10:
        raise ValueError("La fecha debe tener formato YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(valor)
    except ValueError as exc:
        raise ValueError("Fecha inválida") from exc
    if parsed.isoformat() != valor:
        raise ValueError("La fecha debe tener formato YYYY-MM-DD")
    return parsed


def minutos_hhmm(valor):
    if not isinstance(valor, str) or not HHMM_RE.fullmatch(valor):
        raise ValueError("Horas deben tener formato HH:00 o HH:30")
    horas, minutos = map(int, valor.split(":"))
    return horas * 60 + minutos


def validar_intervalos(intervalos):
    if not isinstance(intervalos, list) or not 1 <= len(intervalos) <= 6:
        raise ValueError("Se requieren entre 1 y 6 intervalos")
    ordenados = []
    for intervalo in intervalos:
        if not isinstance(intervalo, dict) or set(intervalo) != {"inicio", "fin"}:
            raise ValueError("Cada intervalo requiere inicio y fin")
        inicio = minutos_hhmm(intervalo["inicio"])
        # Se acepta 24:00 exclusivamente como final de jornada.
        fin_raw = intervalo["fin"]
        fin = 1440 if fin_raw == "24:00" else minutos_hhmm(fin_raw)
        if inicio >= fin:
            raise ValueError("Cada intervalo debe terminar después de comenzar")
        ordenados.append((inicio, fin, intervalo))
    ordenados.sort(key=lambda x: x[0])
    for previo, siguiente in zip(ordenados, ordenados[1:]):
        if previo[1] > siguiente[0]:
            raise ValueError("Los intervalos no deben superponerse")
    return [i[2] for i in ordenados]


def guardar_jornada(event, context):
    tenant, error = autenticado(event)
    if error:
        return error
    try:
        tecnico_id = id_param(event)
        fecha = (event.get("pathParameters") or {}).get("fecha", "")
        fecha_iso(fecha)
        datos = datos_json(event, {"intervalos"})
        intervalos = validar_intervalos(datos.get("intervalos"))
    except ValueError as exc:
        return respuesta(400, {"error": str(exc)})

    tecnico = tecnico_de(tenant, tecnico_id)
    if not tecnico:
        return respuesta(404, {"error": "Técnico no encontrado"})
    if not tecnico.get("activo"):
        return respuesta(409, {"error": "Técnico inactivo"})
    item = {
        "PK": f"TENANT#{tenant}",
        "SK": f"JORNADA#{tecnico_id}#{fecha}",
        "entity_type": "JORNADA",
        "tenant_id": tenant,
        "tecnico_id": tecnico_id,
        "fecha": fecha,
        "zona_horaria": "America/Lima",
        "intervalos": intervalos,
        "actualizado_en": datetime.now(timezone.utc).isoformat(),
    }
    TABLE.put_item(Item=item)  # Versión inicial: reemplaza jornada de esa fecha.
    return respuesta(200, {"jornada": publico_jornada(item)})


def listar_jornadas(event, context):
    tenant, error = autenticado(event)
    if error:
        return error
    try:
        tecnico_id = id_param(event)
        query = event.get("queryStringParameters") or {}
        desde = fecha_iso(query.get("desde"))
        hasta = fecha_iso(query.get("hasta"))
        if hasta < desde or hasta - desde > timedelta(days=30):
            raise ValueError("El rango debe ser de 1 a 31 días")
    except ValueError as exc:
        return respuesta(400, {"error": str(exc)})

    if not tecnico_de(tenant, tecnico_id):
        return respuesta(404, {"error": "Técnico no encontrado"})
    prefijo = f"JORNADA#{tecnico_id}#"
    items = TABLE.query(
        KeyConditionExpression=(
            Key("PK").eq(f"TENANT#{tenant}") &
            Key("SK").between(prefijo + desde.isoformat(), prefijo + hasta.isoformat())
        ),
        Limit=31,
        ConsistentRead=True,
    )
    return respuesta(200, {"jornadas": [publico_jornada(i) for i in items.get("Items", [])]})
