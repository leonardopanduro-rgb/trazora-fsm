"""Crea por única vez el primer ADMIN de una empresa en el entorno dev."""
import argparse
import getpass
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "usuarios"))
from security import hash_password  # noqa: E402

TENANTS = ("CLIMALIMA", "FRIOSUR", "TECNINORTE")

def main():
    parser = argparse.ArgumentParser(description="Bootstrap seguro de administrador (solo dev)")
    parser.add_argument("--tenant", required=True, choices=TENANTS)
    parser.add_argument("--email", required=True)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    email = args.email.strip().lower()
    if not email or "@" not in email or len(email) > 254:
        parser.error("Correo inválido")
    password = getpass.getpass("Contraseña ADMIN (12-128 caracteres): ")
    repeated = getpass.getpass("Repetir contraseña: ")
    if password != repeated:
        parser.error("Las contraseñas no coinciden")
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        parser.error(str(exc))

    user_id = str(uuid.uuid4())
    tenant = args.tenant
    pk = f"TENANT#{tenant}"
    db = boto3.client("dynamodb", region_name=args.region)
    table = "trazora-usuarios-dev"
    created = datetime.now(timezone.utc).isoformat()

    def s(value):
        return {"S": value}

    db.transact_write_items(TransactItems=[
        {"Put": {
            "TableName": table,
            "Item": {
                "PK": s(pk), "SK": s(f"USUARIO#{user_id}"), "entity_type": s("USUARIO"),
                "tenant_id": s(tenant), "usuario_id": s(user_id),
                "email_normalizado": s(email), "rol": s("ADMIN"),
                "estado": s("ACTIVO"), "password_hash": s(password_hash),
                "creado_en": s(created),
            },
            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
        }},
        {"Put": {
            "TableName": table,
            "Item": {
                "PK": s(pk), "SK": s(f"LOGIN#{email}"),
                "entity_type": s("LOGIN"), "usuario_id": s(user_id),
            },
            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
        }},
        {"Put": {
            "TableName": table,
            "Item": {"PK": s(pk), "SK": s("BOOTSTRAP#ADMIN"), "entity_type": s("BOOTSTRAP")},
            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
        }},
    ])
    print(f"Administrador creado: {tenant} / {email} (usuario_id={user_id})")
    print("No se ha mostrado ni guardado la contraseña en el código.")


if __name__ == "__main__":
    main()
