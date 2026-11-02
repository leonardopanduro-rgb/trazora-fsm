"""Mantenimiento DEV: restablecer contraseña de ADMIN existente, sin crear usuarios.

Ejecutar desde EC2 con credenciales de AWS Academy autorizadas.
No utilizar como endpoint público.
"""
import argparse
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "usuarios"))
from security import hash_password  # noqa: E402

TENANTS = ("CLIMALIMA", "FRIOSUR", "TECNINORTE")
TABLE_NAME = "trazora-usuarios-dev"


def main():
    parser = argparse.ArgumentParser(description="Restablecer contraseña ADMIN (solo dev)")
    parser.add_argument("--tenant", required=True, choices=TENANTS)
    parser.add_argument("--email", required=True)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    tenant = args.tenant
    email = args.email.strip().lower()
    if not email or "@" not in email or len(email) > 254:
        parser.error("Correo inválido")

    session = boto3.Session(region_name=args.region)
    account = session.client("sts").get_caller_identity()["Account"]
    table = session.resource("dynamodb").Table(TABLE_NAME)

    pk = f"TENANT#{tenant}"
    marker = table.get_item(
        Key={"PK": pk, "SK": f"LOGIN#{email}"},
        ConsistentRead=True,
    ).get("Item")
    if not marker or not marker.get("usuario_id"):
        print("No se encontró ese correo en el tenant indicado; no se modificó nada.")
        return 1

    usuario_id = marker["usuario_id"]
    user_key = {"PK": pk, "SK": f"USUARIO#{usuario_id}"}
    user = table.get_item(Key=user_key, ConsistentRead=True).get("Item")
    if (not user or user.get("rol") != "ADMIN" or
            user.get("estado") != "ACTIVO" or
            user.get("email_normalizado") != email):
        print("El usuario no es un ADMIN activo con ese correo. Sin cambios.")
        return 1

    print(f"Cuenta AWS: {account} | Región: {args.region}")
    print(f"Tabla: {TABLE_NAME} | Tenant: {tenant} | Correo: {email}")
    confirmation = input(f"Para confirmar escribe exactamente {tenant}: ").strip()
    if confirmation != tenant:
        print("Cancelado sin cambios.")
        return 1

    new_password = getpass.getpass("Nueva contraseña ADMIN (12-128 caracteres): ")
    repeated = getpass.getpass("Repetir nueva contraseña: ")
    if new_password != repeated:
        print("No coinciden. Cancelado sin cambios.")
        return 1
    try:
        password_hash = hash_password(new_password)
    except ValueError as exc:
        print(f"No se realizó el cambio: {exc}")
        return 1
    finally:
        del new_password, repeated

    try:
        table.update_item(
            Key=user_key,
            UpdateExpression=(
                "SET password_hash = :hash, password_changed_at = :when "
                "ADD credential_version :one"
            ),
            ConditionExpression=(
                "attribute_exists(PK) AND attribute_exists(SK) AND "
                "email_normalizado = :email AND #rol = :admin AND #estado = :activo"
            ),
            ExpressionAttributeNames={"#rol": "rol", "#estado": "estado"},
            ExpressionAttributeValues={
                ":hash": password_hash,
                ":when": datetime.now(timezone.utc).isoformat(),
                ":one": 1,
                ":email": email,
                ":admin": "ADMIN",
                ":activo": "ACTIVO",
            },
        )
    except ClientError as exc:
        print("DynamoDB rechazó el cambio:", exc.response.get("Error", {}).get("Code", "Error"))
        return 1

    print("Contraseña restablecida para", tenant, "/", email)
    print("Las sesiones anteriores se invalidan con el autorizador actualizado.")
    print("No se mostró ni guardó la contraseña en texto plano.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado sin guardar cambios adicionales.")
        sys.exit(1)
