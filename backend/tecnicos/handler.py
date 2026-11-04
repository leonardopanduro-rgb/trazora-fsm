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
import urllib.error
import urllib.request
from botocore.exceptions import ClientError
from datetime import date, datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE = boto3.resource("dynamodb").Table(os.environ["TECNICOS_TABLE"])
AGENDA_API_BASE = os.environ["AGENDA_API_BASE"].rstrip("/")
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



def comprobar_reservas_en_agenda(tecnico_id, autorizacion):
    """Consulta en MS4 los bloques actualmente reservados o futuros.

    Fail-closed: si Agenda no responde, no se permite desactivar al técnico.
    La consulta usa el token del solicitante y el tenant del autorizador MS4.
    """
    req = urllib.request.Request(
        AGENDA_API_BASE + "/tecnicos/" + tecnico_id + "/reservas-futuras",
        headers={"Authorization": autorizacion, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as result:
            if result.status != 200:
                return None
            payload = json.load(result)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if isinstance(payload, dict) and type(payload.get("tiene_reservas")) is bool:
        return payload["tiene_reservas"]
    return None


def cambiar_estado(event, context):
    """ADMIN puede activar o desactivar un técnico de su propia empresa.

    Para desactivar se consulta MS4. Nunca se desactiva si la verificación
    de reservas falla o detecta alguna reserva futura/en curso.
    """
    tenant, error = autenticado(event)
    if error:
        return error
    claims = (event.get("requestContext") or {}).get("authorizer") or {}
    if claims.get("rol") != "ADMIN":
        return respuesta(403, {"error": "Solo ADMIN puede cambiar el estado"})

    try:
        tecnico_id = id_param(event)
        datos = datos_json(event, {"activo"})
        if set(datos) != {"activo"} or type(datos["activo"]) is not bool:
            raise ValueError("Se requiere activo con valor booleano true o false")
    except ValueError as exc:
        return respuesta(400, {"error": str(exc)})

    tecnico = tecnico_de(tenant, tecnico_id)
    if not tecnico:
        return respuesta(404, {"error": "Técnico no encontrado"})

    activo_actual = tecnico.get("activo")
    nuevo_estado = datos["activo"]
    if type(activo_actual) is not bool:
        return respuesta(409, {"error": "El estado del técnico es inconsistente"})
    if activo_actual == nuevo_estado:
        return respuesta(200, {"tecnico": publico_tecnico(tecnico), "sin_cambios": True})

    if nuevo_estado is False:
        auth = next((
            value for key, value in (event.get("headers") or {}).items()
            if isinstance(key, str) and key.lower() == "authorization"
        ), None)
        if not isinstance(auth, str) or not auth.lower().startswith("bearer "):
            return respuesta(401, {"error": "Falta token de autorización"})

        tiene_reservas = comprobar_reservas_en_agenda(tecnico_id, auth)
        if tiene_reservas is None:
            return respuesta(503, {"error": "No se pudo comprobar reservas en Agenda"})
        if tiene_reservas:
            return respuesta(409, {"error": "El técnico tiene visitas reservadas, cancélalas o reasígnalas antes"})

    try:
        resultado = TABLE.update_item(
            Key={"PK": f"TENANT#{tenant}", "SK": f"TECNICO#{tecnico_id}"},
            UpdateExpression="SET #activo = :nuevo, actualizado_en = :ahora",
            ConditionExpression="attribute_exists(PK) AND #activo = :anterior",
            ExpressionAttributeNames={"#activo": "activo"},
            ExpressionAttributeValues={
                ":nuevo": nuevo_estado,
                ":anterior": activo_actual,
                ":ahora": datetime.now(timezone.utc).isoformat(),
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return respuesta(409, {"error": "El estado cambió, vuelve a consultar al técnico"})
        print("Error actualizando estado técnico:", code)
        return respuesta(500, {"error": "No se pudo actualizar el técnico"})
    return respuesta(200, {"tecnico": publico_tecnico(resultado["Attributes"]), "sin_cambios": False})


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
