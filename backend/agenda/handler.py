"""MS4 Agenda: primera versión de programación atómica de visitas por empresa.

Usa el autorizador de MS0 y consulta MS2/MS3 a través de sus APIs protegidas.
Guarda reservas de bloques de media hora mediante TransactWriteItems.
"""
import base64
import binascii
import json
import os
import re
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["AGENDA_TABLE"]
ORDENES_API = os.environ["ORDENES_API_BASE"].rstrip("/")
TECNICOS_API = os.environ["TECNICOS_API_BASE"].rstrip("/")
TABLE = boto3.resource("dynamodb").Table(TABLE_NAME)
DB_CLIENT = boto3.client("dynamodb")
SER = TypeSerializer()

LIMA = ZoneInfo("America/Lima")
ALLOWED_TENANTS = {"CLIMALIMA", "FRIOSUR", "TECNINORTE"}
COORD_ROLES = {"ADMIN", "COORDINADOR"}
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:(00|30):00Z$")


def response(status, data):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
        },
        "body": json.dumps(data, ensure_ascii=False),
    }


def principal(event):
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    tenant = authorizer.get("tenant_id")
    user = authorizer.get("usuario_id")
    if tenant not in ALLOWED_TENANTS or not user:
        return None, response(401, {"error": "No autorizado"})
    if authorizer.get("rol") not in COORD_ROLES:
        return None, response(403, {"error": "El rol no tiene acceso a Agenda"})
    return tenant, None


def bearer(event):
    header = next((
        v for k, v in (event.get("headers") or {}).items()
        if isinstance(k, str) and k.lower() == "authorization"
    ), None)
    if not isinstance(header, str) or not header.lower().startswith("bearer "):
        return None
    return header


def get_protegido(base_url, path, auth):
    req = urllib.request.Request(
        base_url + path,
        headers={"Authorization": auth, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as result:
            if result.status != 200:
                return None, 502
            return json.load(result), 200
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            return None, exc.code
        return None, 502
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None, 502


def parse_instant(value):
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise ValueError("Usa fecha UTC en formato YYYY-MM-DDTHH:MM:00Z, minutos 00 o 30")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Fecha UTC inválida") from exc


def validar_horario(inicio_raw, fin_raw):
    inicio = parse_instant(inicio_raw)
    fin = parse_instant(fin_raw)
    if inicio <= datetime.now(timezone.utc):
        raise ValueError("La visita debe programarse para el futuro")
    minutos = (fin - inicio).total_seconds() / 60
    if minutos < 30 or minutos > 240 or minutos % 30 != 0:
        raise ValueError("Duración permitida: de 30 minutos a 4 horas en bloques de 30")
    inicio_lima, fin_lima = inicio.astimezone(LIMA), fin.astimezone(LIMA)
    if inicio_lima.date() != fin_lima.date():
        raise ValueError("La visita debe comenzar y terminar el mismo día en Lima")
    return inicio, fin, inicio_lima, fin_lima


def dentro_jornada(inicio_lima, fin_lima, intervalos):
    comienzo = inicio_lima.hour * 60 + inicio_lima.minute
    termino = fin_lima.hour * 60 + fin_lima.minute
    if (fin_lima.hour == 0 and fin_lima.minute == 0 and
            fin_lima.date() > inicio_lima.date()):
        termino = 1440
    for intervalo in intervalos:
        try:
            desde = intervalo["inicio"]
            hasta = intervalo["fin"]
            a = int(desde[:2]) * 60 + int(desde[3:])
            b = 1440 if hasta == "24:00" else int(hasta[:2]) * 60 + int(hasta[3:])
            if a <= comienzo and termino <= b:
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return False


def attr(value):
    return SER.serialize(value)


def dinamodb_item(item):
    return {key: attr(value) for key, value in item.items()}


def public(item):
    keys = (
        "visita_id", "tenant_id", "orden_id", "tecnico_id", "inicio",
        "fin", "estado", "creada_en", "version", "iniciada_en",
        "reprogramada_en", "cancelada_en",
    )
    values = {key: item.get(key) for key in keys if key in item}
    if "version" in values:
        values["version"] = int(values["version"])
    return values


def crear(event, context):
    tenant, error = principal(event)
    if error:
        return error
    try:
        body = json.loads(event.get("body") or "{}")
        if not isinstance(body, dict) or set(body) != {
            "orden_id", "tecnico_id", "inicio", "fin"
        }:
            raise ValueError("Campos inválidos: se requieren orden_id, tecnico_id, inicio y fin")
        orden_id, tecnico_id = body["orden_id"], body["tecnico_id"]
        if not isinstance(orden_id, str) or not UUID_RE.fullmatch(orden_id):
            raise ValueError("orden_id inválido")
        if not isinstance(tecnico_id, str) or not UUID_RE.fullmatch(tecnico_id):
            raise ValueError("tecnico_id inválido")
        inicio, fin, inicio_lima, fin_lima = validar_horario(body["inicio"], body["fin"])
    except (ValueError, TypeError, KeyError) as exc:
        return response(400, {"error": str(exc)})

    auth = bearer(event)
    if not auth:
        return response(401, {"error": "No autorizado"})
    order_result, status = get_protegido(ORDENES_API, "/ordenes/" + orden_id, auth)
    if status != 200:
        return response(
            404 if status == 404 else 401 if status in (401, 403) else 502,
            {"error": "No se pudo validar la orden"},
        )
    orden = order_result.get("orden", {}) if isinstance(order_result, dict) else {}
    if orden.get("orden_id") != orden_id or orden.get("tenant_id") != tenant:
        return response(404, {"error": "Orden no encontrada"})
    if orden.get("estado") != "ABIERTA":
        return response(409, {"error": "La orden no admite nuevas visitas"})

    tech_result, status = get_protegido(TECNICOS_API, "/tecnicos/" + tecnico_id, auth)
    if status != 200:
        return response(
            404 if status == 404 else 401 if status in (401, 403) else 502,
            {"error": "No se pudo validar el técnico"},
        )
    tecnico = tech_result.get("tecnico", {}) if isinstance(tech_result, dict) else {}
    if tecnico.get("tecnico_id") != tecnico_id or tecnico.get("tenant_id") != tenant:
        return response(404, {"error": "Técnico no encontrado"})
    if tecnico.get("activo") is not True:
        return response(409, {"error": "Técnico inactivo"})
    if orden.get("tipo_servicio") not in tecnico.get("especialidades", []):
        return response(422, {"error": "Técnico sin especialidad para el servicio"})

    fecha_lima = inicio_lima.date().isoformat()
    jornadas_result, status = get_protegido(
        TECNICOS_API,
        f"/tecnicos/{tecnico_id}/jornadas?desde={fecha_lima}&hasta={fecha_lima}",
        auth,
    )
    if status != 200:
        return response(
            404 if status == 404 else 401 if status in (401, 403) else 502,
            {"error": "No se pudo consultar la jornada del técnico"},
        )
    jornadas = jornadas_result.get("jornadas", []) if isinstance(jornadas_result, dict) else []
    valida = any(
        jornada.get("fecha") == fecha_lima
        and jornada.get("tenant_id") == tenant
        and jornada.get("tecnico_id") == tecnico_id
        and dentro_jornada(inicio_lima, fin_lima, jornada.get("intervalos", []))
        for jornada in jornadas
    )
    if not valida:
        return response(409, {"error": "Horario fuera de la jornada del técnico"})

    visita_id = str(uuid.uuid4())
    pk = f"TENANT#{tenant}"
    item = {
        "PK": pk, "SK": f"VISITA#{visita_id}", "entity_type": "VISITA",
        "visita_id": visita_id, "tenant_id": tenant,
        "orden_id": orden_id, "tecnico_id": tecnico_id,
        "inicio": body["inicio"], "fin": body["fin"],
        "estado": "PROGRAMADA", "creada_en": datetime.now(timezone.utc).isoformat(),
        "version": 1,
    }
    actions = [
        {"Put": {
            "TableName": TABLE_NAME,
            "Item": dinamodb_item(item),
            "ConditionExpression": "attribute_not_exists(PK)",
        }}
    ]
    cursor = inicio
    while cursor < fin:
        slot = cursor.isoformat(timespec="seconds").replace("+00:00", "Z")
        bloque = {
            "PK": pk,
            "SK": f"BLOQUE#{tecnico_id}#{slot}",
            "entity_type": "BLOQUE",
            "tenant_id": tenant,
            "tecnico_id": tecnico_id,
            "visita_id": visita_id,
        }
        actions.append({"Put": {
            "TableName": TABLE_NAME,
            "Item": dinamodb_item(bloque),
            "ConditionExpression": "attribute_not_exists(PK)",
        }})
        cursor += timedelta(minutes=30)

    # El control por orden se crea o actualiza en la MISMA transacción que los bloques.
    # Un cierre futuro podrá bloquear nuevas reservas poniendo acepta_programaciones=False.
    actions.append({"Update": {
        "TableName": TABLE_NAME,
        "Key": dinamodb_item({"PK": pk, "SK": f"CONTROL_ORDEN#{orden_id}"}),
        "UpdateExpression": (
            "SET entity_type = if_not_exists(entity_type, :tipo), "
            "orden_id = if_not_exists(orden_id, :orden), "
            "acepta_programaciones = if_not_exists(acepta_programaciones, :abierto) "
            "ADD visitas_activas :uno"
        ),
        "ConditionExpression": (
            "attribute_not_exists(acepta_programaciones) OR acepta_programaciones = :abierto"
        ),
        "ExpressionAttributeValues": dinamodb_item({
            ":tipo": "CONTROL_ORDEN",
            ":orden": orden_id,
            ":abierto": True,
            ":uno": 1,
        }),
    }})
    try:
        DB_CLIENT.transact_write_items(TransactItems=actions)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("TransactionCanceledException", "ConditionalCheckFailedException"):
            return response(409, {"error": "El horario ya está reservado o la orden está bloqueada"})
        # No revelar mensajes de AWS ni credenciales; código visible en CloudWatch.
        print("Fallo creando visita: DynamoDB", code)
        return response(500, {"error": "No se pudo guardar la visita"})
    return response(201, {"visita": public(item)})


def listar(event, context):
    tenant, error = principal(event)
    if error:
        return error
    params = event.get("queryStringParameters") or {}
    try:
        limit = int(params.get("limit", "20"))
        if limit < 1 or limit > 50:
            raise ValueError()
    except (TypeError, ValueError):
        return response(400, {"error": "limit debe estar entre 1 y 50"})
    pk = f"TENANT#{tenant}"
    query = {
        "KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with("VISITA#"),
        "Limit": limit,
        "ConsistentRead": True,
    }
    if params.get("cursor"):
        try:
            raw = params["cursor"]
            if not isinstance(raw, str) or not 1 <= len(raw) <= 128:
                raise ValueError()
            sk = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("ascii")
            if not sk.startswith("VISITA#") or not UUID_RE.fullmatch(sk[7:]):
                raise ValueError()
            query["ExclusiveStartKey"] = {"PK": pk, "SK": sk}
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return response(400, {"error": "Cursor inválido"})
    data = TABLE.query(**query)
    last = data.get("LastEvaluatedKey")
    next_cursor = None
    if last:
        next_cursor = base64.urlsafe_b64encode(last["SK"].encode("ascii")).decode("ascii").rstrip("=")
    return response(200, {
        "visitas": [public(item) for item in data.get("Items", [])],
        "next_cursor": next_cursor,
    })



def reservas_futuras(event, context):
    """Indica si el técnico tiene algún bloque reservado ahora o después.

    Consulta por clave, sin scan, usando el índice de ordenación actual
    BLOQUE#<tecnico_id>#<inicio_utc>. Una visita de hasta 4h tiene un
    BLOQUE cada media hora. Se incluye el bloque de la media hora en curso.
    """
    tenant, error = principal(event)
    if error:
        return error
    tecnico_id = (event.get("pathParameters") or {}).get("tecnico_id", "")
    if not isinstance(tecnico_id, str) or not UUID_RE.fullmatch(tecnico_id):
        return response(400, {"error": "tecnico_id inválido"})

    fecha = datetime.now(timezone.utc)
    comienzo = fecha.replace(minute=(fecha.minute // 30) * 30, second=0, microsecond=0)
    prefijo = f"BLOQUE#{tecnico_id}#"
    desde = prefijo + comienzo.isoformat(timespec="seconds").replace("+00:00", "Z")
    resultado = TABLE.query(
        KeyConditionExpression=(
            Key("PK").eq(f"TENANT#{tenant}") &
            Key("SK").between(desde, prefijo + "\uffff")
        ),
        ConsistentRead=True,
        Limit=1,
    )
    return response(200, {
        "tecnico_id": tecnico_id,
        "tiene_reservas": bool(resultado.get("Items")),
    })




def visita_de(tenant, visita_id):
    return TABLE.get_item(
        Key={"PK": f"TENANT#{tenant}", "SK": f"VISITA#{visita_id}"},
        ConsistentRead=True,
    ).get("Item")


def visita_id_de(event):
    visita_id = (event.get("pathParameters") or {}).get("visita_id", "")
    if not isinstance(visita_id, str) or not UUID_RE.fullmatch(visita_id):
        raise ValueError("visita_id inválido")
    return visita_id


def cuerpo_exacto(event, campos):
    try:
        datos = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError) as exc:
        raise ValueError("JSON inválido") from exc
    if not isinstance(datos, dict) or set(datos) != campos:
        raise ValueError("Campos inválidos: " + ", ".join(sorted(campos)))
    return datos


def lectura_version(item):
    """Compatibilidad con visitas antiguas, creadas sin version."""
    from decimal import Decimal
    version = item.get("version")
    if version is None:
        return 1, True
    if (isinstance(version, bool) or
            not isinstance(version, (int, Decimal)) or
            not 1 <= version <= 2_000_000_000 or version != int(version)):
        raise ValueError("Versión de visita incompatible")
    return int(version), False


def condicion_programada(item, extra=None):
    version, antigua = lectura_version(item)
    cond = ("#estado = :programada AND tecnico_id = :anterior_tecnico "
            "AND inicio = :anterior_inicio AND fin = :anterior_fin "
            "AND " + ("attribute_not_exists(#version)" if antigua else "#version = :esperada"))
    nombres = {"#estado": "estado", "#version": "version"}
    valores = {
        ":programada": "PROGRAMADA",
        ":anterior_tecnico": item["tecnico_id"],
        ":anterior_inicio": item["inicio"],
        ":anterior_fin": item["fin"],
    }
    if not antigua:
        valores[":esperada"] = version
    return cond, nombres, valores, version


def slots_visita(tecnico_id, inicio_raw, fin_raw):
    """Conjunto de SK de bloques de 30 minutos; no aplica validación futura."""
    inicio = parse_instant(inicio_raw)
    fin = parse_instant(fin_raw)
    if not inicio < fin or (fin - inicio).total_seconds() % 1800:
        raise ValueError("Bloques de visita inconsistentes")
    bloques = set()
    instante = inicio
    while instante < fin:
        stamp = instante.isoformat(timespec="seconds").replace("+00:00", "Z")
        bloques.add(f"BLOQUE#{tecnico_id}#{stamp}")
        instante += timedelta(minutes=30)
    if len(bloques) > 8:
        raise ValueError("Demasiados bloques en la visita")
    return bloques


def ejecutar_transaccion(acciones, operacion):
    try:
        DB_CLIENT.transact_write_items(TransactItems=acciones)
        return None
    except ClientError as exc:
        codigo = exc.response.get("Error", {}).get("Code")
        if codigo in ("TransactionCanceledException", "ConditionalCheckFailedException"):
            return response(409, {"error": f"Conflicto al {operacion}: actualiza la visita o revisa las reservas"})
        print("Error DynamoDB en ciclo de visita:", operacion, codigo)
        return response(500, {"error": "No se pudo completar la operación"})


def validar_asignacion(tenant, orden_id, tecnico_id, inicio_lima, fin_lima, auth):
    """Valida referencias por API; jamás lee las tablas de MS2/MS3."""
    orden_res, status = get_protegido(ORDENES_API, "/ordenes/" + orden_id, auth)
    if status != 200:
        return response(
            404 if status == 404 else 401 if status in (401, 403) else 502,
            {"error": "No se pudo validar la orden"},
        )
    orden = orden_res.get("orden", {}) if isinstance(orden_res, dict) else {}
    if orden.get("tenant_id") != tenant or orden.get("orden_id") != orden_id:
        return response(404, {"error": "Orden no encontrada"})
    if orden.get("estado") != "ABIERTA":
        return response(409, {"error": "La orden no admite cambios de agenda"})

    tech_res, status = get_protegido(TECNICOS_API, "/tecnicos/" + tecnico_id, auth)
    if status != 200:
        return response(
            404 if status == 404 else 401 if status in (401, 403) else 502,
            {"error": "No se pudo validar el técnico"},
        )
    tecnico = tech_res.get("tecnico", {}) if isinstance(tech_res, dict) else {}
    if tecnico.get("tenant_id") != tenant or tecnico.get("tecnico_id") != tecnico_id:
        return response(404, {"error": "Técnico no encontrado"})
    if tecnico.get("activo") is not True:
        return response(409, {"error": "Técnico inactivo"})
    if orden.get("tipo_servicio") not in tecnico.get("especialidades", []):
        return response(422, {"error": "Técnico sin especialidad para la orden"})

    dia = inicio_lima.date().isoformat()
    jorn_res, status = get_protegido(
        TECNICOS_API,
        f"/tecnicos/{tecnico_id}/jornadas?desde={dia}&hasta={dia}",
        auth,
    )
    if status != 200:
        return response(
            404 if status == 404 else 401 if status in (401, 403) else 502,
            {"error": "No se pudo validar la jornada"},
        )
    jornadas = jorn_res.get("jornadas", []) if isinstance(jorn_res, dict) else []
    valido = any(
        isinstance(j, dict) and
        j.get("fecha") == dia and
        j.get("tenant_id") == tenant and
        j.get("tecnico_id") == tecnico_id and
        dentro_jornada(inicio_lima, fin_lima, j.get("intervalos", []))
        for j in jornadas
    )
    if not valido:
        return response(409, {"error": "Horario fuera de la jornada del técnico"})
    return None


def iniciar(event, context):
    """PROGRAMADA -> EN_ATENCION, con control de concurrencia e idempotencia."""
    tenant, error = principal(event)
    if error:
        return error
    try:
        visita_id = visita_id_de(event)
        cuerpo_exacto(event, set())
    except ValueError as exc:
        return response(400, {"error": str(exc)})
    item = visita_de(tenant, visita_id)
    if not item:
        return response(404, {"error": "Visita no encontrada"})
    if item.get("estado") == "EN_ATENCION":
        return response(200, {"visita": public(item), "sin_cambios": True})
    if item.get("estado") != "PROGRAMADA":
        return response(409, {"error": "La visita no se puede iniciar en su estado actual"})
    try:
        condicion, nombres, valores, version = condicion_programada(item)
    except (ValueError, KeyError):
        return response(409, {"error": "Visita inconsistente"})
    momento = datetime.now(timezone.utc).isoformat()
    nombres["#estado"] = "estado"
    valores.update({
        ":nuevo_estado": "EN_ATENCION",
        ":nueva_version": version + 1,
        ":momento": momento,
    })
    try:
        resultado = TABLE.update_item(
            Key={"PK": f"TENANT#{tenant}", "SK": f"VISITA#{visita_id}"},
            UpdateExpression=(
                "SET #estado = :nuevo_estado, #version = :nueva_version, iniciada_en = :momento"
            ),
            ConditionExpression=condicion,
            ExpressionAttributeNames=nombres,
            ExpressionAttributeValues=valores,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return response(409, {"error": "La visita cambió mientras se intentaba iniciar"})
        print("Error al iniciar visita:", exc.response.get("Error", {}).get("Code"))
        return response(500, {"error": "No se pudo iniciar la visita"})
    return response(200, {"visita": public(resultado["Attributes"]), "sin_cambios": False})


def reprogramar(event, context):
    """Cambia técnico/horario, moviendo bloques atómicamente sin tocar el contador."""
    tenant, error = principal(event)
    if error:
        return error
    try:
        visita_id = visita_id_de(event)
        datos = cuerpo_exacto(event, {"tecnico_id", "inicio", "fin"})
        tecnico_id = datos["tecnico_id"]
        if not isinstance(tecnico_id, str) or not UUID_RE.fullmatch(tecnico_id):
            raise ValueError("tecnico_id inválido")
        _, _, inicio_lima, fin_lima = validar_horario(datos["inicio"], datos["fin"])
    except (ValueError, TypeError) as exc:
        return response(400, {"error": str(exc)})

    item = visita_de(tenant, visita_id)
    if not item:
        return response(404, {"error": "Visita no encontrada"})
    if item.get("estado") != "PROGRAMADA":
        return response(409, {"error": "Solo puede reprogramarse una visita PROGRAMADA"})

    if (item.get("tecnico_id"), item.get("inicio"), item.get("fin")) == (
            tecnico_id, datos["inicio"], datos["fin"]):
        return response(200, {"visita": public(item), "sin_cambios": True})

    auth = bearer(event)
    if not auth:
        return response(401, {"error": "No autorizado"})
    orden_id = item.get("orden_id")
    if not isinstance(orden_id, str) or not UUID_RE.fullmatch(orden_id):
        return response(409, {"error": "Orden de visita inconsistente"})
    error = validar_asignacion(
        tenant, orden_id, tecnico_id, inicio_lima, fin_lima, auth
    )
    if error:
        return error
    try:
        viejos = slots_visita(item["tecnico_id"], item["inicio"], item["fin"])
        nuevos = slots_visita(tecnico_id, datos["inicio"], datos["fin"])
        condicion, nombres, valores, version = condicion_programada(item)
    except (ValueError, KeyError):
        return response(409, {"error": "Bloques antiguos inconsistentes"})
    momento = datetime.now(timezone.utc).isoformat()
    pk = f"TENANT#{tenant}"
    valores.update({
        ":nuevo_tecnico": tecnico_id,
        ":nuevo_inicio": datos["inicio"],
        ":nuevo_fin": datos["fin"],
        ":nueva_version": version + 1,
        ":momento": momento,
    })
    acciones = [{
        "Update": {
            "TableName": TABLE_NAME,
            "Key": dinamodb_item({"PK": pk, "SK": f"VISITA#{visita_id}"}),
            "UpdateExpression": (
                "SET tecnico_id = :nuevo_tecnico, inicio = :nuevo_inicio, "
                "fin = :nuevo_fin, #version = :nueva_version, reprogramada_en = :momento"
            ),
            "ConditionExpression": condicion,
            "ExpressionAttributeNames": nombres,
            "ExpressionAttributeValues": dinamodb_item(valores),
        },
    }]
    # No se puede modificar un mismo ítem dos veces en una TransactWriteItems.
    # Los bloques comunes de ambos horarios quedan intactos.
    for sk in sorted(viejos - nuevos):
        acciones.append({"Delete": {
            "TableName": TABLE_NAME,
            "Key": dinamodb_item({"PK": pk, "SK": sk}),
            "ConditionExpression": "visita_id = :visita",
            "ExpressionAttributeValues": dinamodb_item({":visita": visita_id}),
        }})
    for sk in sorted(nuevos - viejos):
        partes = sk.split("#")
        acciones.append({"Put": {
            "TableName": TABLE_NAME,
            "Item": dinamodb_item({
                "PK": pk, "SK": sk, "entity_type": "BLOQUE",
                "tenant_id": tenant, "tecnico_id": tecnico_id, "visita_id": visita_id,
            }),
            "ConditionExpression": "attribute_not_exists(PK)",
        }})
    # Un bloqueo de cierre de MS3 puede impedir reprogramaciones nuevas.
    acciones.append({"ConditionCheck": {
        "TableName": TABLE_NAME,
        "Key": dinamodb_item({"PK": pk, "SK": f"CONTROL_ORDEN#{orden_id}"}),
        "ConditionExpression": "attribute_exists(PK) AND acepta_programaciones = :abierto",
        "ExpressionAttributeValues": dinamodb_item({":abierto": True}),
    }})
    error = ejecutar_transaccion(acciones, "reprogramar")
    if error:
        return error
    nuevo = dict(item, **{
        "tecnico_id": tecnico_id, "inicio": datos["inicio"], "fin": datos["fin"],
        "version": version + 1, "reprogramada_en": momento,
    })
    return response(200, {"visita": public(nuevo), "sin_cambios": False})


def cancelar(event, context):
    """Cancela visita PROGRAMADA, libera todos los bloques y decrementa una vez."""
    tenant, error = principal(event)
    if error:
        return error
    try:
        visita_id = visita_id_de(event)
        cuerpo_exacto(event, set())
    except ValueError as exc:
        return response(400, {"error": str(exc)})
    item = visita_de(tenant, visita_id)
    if not item:
        return response(404, {"error": "Visita no encontrada"})
    if item.get("estado") == "CANCELADA":
        return response(200, {"visita": public(item), "sin_cambios": True})
    if item.get("estado") != "PROGRAMADA":
        return response(409, {"error": "Solo puede cancelarse una visita PROGRAMADA"})
    try:
        bloques = slots_visita(item["tecnico_id"], item["inicio"], item["fin"])
        condicion, nombres, valores, version = condicion_programada(item)
        orden_id = item["orden_id"]
        if not isinstance(orden_id, str) or not UUID_RE.fullmatch(orden_id):
            raise ValueError("Orden inválida")
    except (KeyError, ValueError):
        return response(409, {"error": "Reservas antiguas inconsistentes"})
    pk = f"TENANT#{tenant}"
    momento = datetime.now(timezone.utc).isoformat()
    valores.update({
        ":nuevo_estado": "CANCELADA",
        ":nueva_version": version + 1,
        ":momento": momento,
    })
    acciones = [{
        "Update": {
            "TableName": TABLE_NAME,
            "Key": dinamodb_item({"PK": pk, "SK": f"VISITA#{visita_id}"}),
            "UpdateExpression": (
                "SET #estado = :nuevo_estado, #version = :nueva_version, cancelada_en = :momento"
            ),
            "ConditionExpression": condicion,
            "ExpressionAttributeNames": nombres,
            "ExpressionAttributeValues": dinamodb_item(valores),
        },
    }]
    for sk in sorted(bloques):
        acciones.append({"Delete": {
            "TableName": TABLE_NAME,
            "Key": dinamodb_item({"PK": pk, "SK": sk}),
            "ConditionExpression": "visita_id = :visita",
            "ExpressionAttributeValues": dinamodb_item({":visita": visita_id}),
        }})
    acciones.append({"Update": {
        "TableName": TABLE_NAME,
        "Key": dinamodb_item({"PK": pk, "SK": f"CONTROL_ORDEN#{orden_id}"}),
        "UpdateExpression": "ADD visitas_activas :menos",
        "ConditionExpression": "attribute_exists(PK) AND visitas_activas >= :uno",
        "ExpressionAttributeValues": dinamodb_item({":menos": -1, ":uno": 1}),
    }})
    error = ejecutar_transaccion(acciones, "cancelar")
    if error:
        return error
    nuevo = dict(item, **{
        "estado": "CANCELADA", "version": version + 1, "cancelada_en": momento,
    })
    return response(200, {"visita": public(nuevo), "sin_cambios": False})

def buscar(event, context):
    tenant, error = principal(event)
    if error:
        return error
    visita_id = (event.get("pathParameters") or {}).get("visita_id", "")
    if not isinstance(visita_id, str) or not UUID_RE.fullmatch(visita_id):
        return response(400, {"error": "visita_id inválido"})
    item = TABLE.get_item(
        Key={"PK": f"TENANT#{tenant}", "SK": f"VISITA#{visita_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not item:
        return response(404, {"error": "Visita no encontrada"})
    return response(200, {"visita": public(item)})
