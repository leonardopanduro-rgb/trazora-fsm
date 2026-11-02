"""MS0: login, perfil, logout y autorizador para API Gateway REST."""
import json
import os
import secrets
import time
from datetime import datetime, timezone

import boto3
from security import token_hash, verify_password

DYNAMODB = boto3.resource("dynamodb")
USUARIOS_TABLE = os.environ["USUARIOS_TABLE"]
SESIONES_TABLE = os.environ["SESIONES_TABLE"]
ALLOWED_TENANTS = set(os.getenv("ALLOWED_TENANTS", "CLIMALIMA,FRIOSUR,TECNINORTE").split(","))
SESSION_SECONDS = 3600

def _reply(code, payload):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(payload),
    }

def health(event, context):
    return _reply(200, {"ok": True, "servicio": "trazora-usuarios"})

def _parse_bearer(raw):
    if not isinstance(raw, str):
        return None
    prefix, sep, token = raw.partition(" ")
    if not sep or prefix.lower() != "bearer" or not (32 <= len(token) <= 256) or " " in token:
        return None
    return token

def _usuario(tenant, usuario_id):
    return DYNAMODB.Table(USUARIOS_TABLE).get_item(
        Key={"PK": f"TENANT#{tenant}", "SK": f"USUARIO#{usuario_id}"},
        ConsistentRead=True,
    ).get("Item")

def login(event, context):
    try:
        data = json.loads(event.get("body") or "{}")
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, TypeError):
        return _reply(400, {"error": "JSON inválido"})
    tenant, email, password = data.get("tenant_id"), data.get("email"), data.get("password")
    if not all(isinstance(x, str) for x in (tenant, email, password)):
        return _reply(400, {"error": "Faltan tenant_id, email o password"})
    tenant, email = tenant.strip().upper(), email.strip().lower()
    if tenant not in ALLOWED_TENANTS or not email or len(email) > 254:
        return _reply(401, {"error": "Credenciales inválidas"})
    table = DYNAMODB.Table(USUARIOS_TABLE)
    marker = table.get_item(
        Key={"PK": f"TENANT#{tenant}", "SK": f"LOGIN#{email}"},
        ConsistentRead=True,
    ).get("Item")
    user = _usuario(tenant, marker["usuario_id"]) if marker and marker.get("usuario_id") else None
    if not user or user.get("estado") != "ACTIVO" or not verify_password(password, user.get("password_hash", "")):
        return _reply(401, {"error": "Credenciales inválidas"})
    raw_token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_SECONDS
    DYNAMODB.Table(SESIONES_TABLE).put_item(
        Item={
            "token_hash": token_hash(raw_token),
            "tenant_id": tenant,
            "usuario_id": user["usuario_id"],
            "revocada": False,
            "expires_at": expires_at,
            "credential_version": int(user.get("credential_version", 0)),
        },
        ConditionExpression="attribute_not_exists(token_hash)",
    )
    return _reply(200, {
        "token": raw_token,
        "token_type": "Bearer",
        "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
        "usuario": {
            "usuario_id": user["usuario_id"], "tenant_id": tenant,
            "email": user["email_normalizado"], "rol": user["rol"],
        },
    })

def authorizer(event, context):
    token = _parse_bearer(event.get("authorizationToken"))
    if not token:
        raise Exception("Unauthorized")
    session = DYNAMODB.Table(SESIONES_TABLE).get_item(
        Key={"token_hash": token_hash(token)}, ConsistentRead=True,
    ).get("Item")
    if not session or session.get("revocada") is True or int(session.get("expires_at", 0)) <= int(time.time()):
        raise Exception("Unauthorized")
    tenant, usuario_id = session.get("tenant_id"), session.get("usuario_id")
    if tenant not in ALLOWED_TENANTS or not usuario_id:
        raise Exception("Unauthorized")
    user = _usuario(tenant, usuario_id)
    if not user or user.get("estado") != "ACTIVO" or user.get("rol") not in ("ADMIN", "COORDINADOR", "TECNICO"):
        raise Exception("Unauthorized")
    if int(session.get("credential_version", 0)) != int(user.get("credential_version", 0)):
        raise Exception("Unauthorized")
    return {
        "principalId": usuario_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "execute-api:Invoke", "Effect": "Allow",
                "Resource": event["methodArn"],
            }],
        },
        "context": {"usuario_id": usuario_id, "tenant_id": tenant, "rol": user["rol"]},
    }

def _principal(event):
    data = (event.get("requestContext") or {}).get("authorizer") or {}
    tenant, user = data.get("tenant_id"), data.get("usuario_id")
    if tenant not in ALLOWED_TENANTS or not user:
        return None
    return tenant, user

def me(event, context):
    principal = _principal(event)
    if not principal:
        return _reply(401, {"error": "No autorizado"})
    tenant, usuario_id = principal
    user = _usuario(tenant, usuario_id)
    if not user or user.get("estado") != "ACTIVO":
        return _reply(401, {"error": "No autorizado"})
    return _reply(200, {
        "usuario_id": user["usuario_id"], "tenant_id": tenant,
        "email": user["email_normalizado"], "rol": user["rol"],
        "estado": user["estado"],
    })

def logout(event, context):
    principal = _principal(event)
    authorization = next(
        (v for k, v in (event.get("headers") or {}).items() if k.lower() == "authorization"), None,
    )
    token = _parse_bearer(authorization)
    if not principal or not token:
        return _reply(401, {"error": "No autorizado"})
    tenant, usuario_id = principal
    try:
        DYNAMODB.Table(SESIONES_TABLE).update_item(
            Key={"token_hash": token_hash(token)},
            UpdateExpression="SET revocada = :true",
            ConditionExpression="tenant_id = :tenant AND usuario_id = :user",
            ExpressionAttributeValues={":true": True, ":tenant": tenant, ":user": usuario_id},
        )
    except DYNAMODB.meta.client.exceptions.ConditionalCheckFailedException:
        return _reply(401, {"error": "No autorizado"})
    return _reply(200, {"ok": True})
