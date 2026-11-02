"""Diagnóstico de login MS0: lectura local de DynamoDB, sin modificar datos."""
import argparse
import getpass
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "usuarios"))
from security import verify_password  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True, choices=("CLIMALIMA", "FRIOSUR", "TECNINORTE"))
    parser.add_argument("--email", required=True)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    tenant = args.tenant
    email = args.email.strip().lower()
    if not email or "@" not in email:
        parser.error("Correo inválido")

    table_name = "trazora-usuarios-dev"
    print("Tabla:", table_name)
    print("Región:", args.region)

    try:
        table = boto3.resource("dynamodb", region_name=args.region).Table(table_name)
        marker = table.get_item(
            Key={"PK": f"TENANT#{tenant}", "SK": f"LOGIN#{email}"},
            ConsistentRead=True,
        ).get("Item")
        print("1. Marcador de correo encontrado:", "SÍ" if marker else "NO")
        if not marker:
            print("No hay marcador para ese tenant/correo. Comprueba exactamente el correo usado en el alta.")
            return 1

        uid = marker.get("usuario_id")
        if not uid:
            print("2. El marcador no contiene usuario_id.")
            return 1
        user = table.get_item(
            Key={"PK": f"TENANT#{tenant}", "SK": f"USUARIO#{uid}"},
            ConsistentRead=True,
        ).get("Item")
        print("2. Registro de usuario encontrado:", "SÍ" if user else "NO")
        if not user:
            return 1

        print("3. Usuario activo:", "SÍ" if user.get("estado") == "ACTIVO" else "NO")
        print("4. Rol:", user.get("rol", "(sin rol)"))
        stored_hash = user.get("password_hash")
        print("5. Contraseña protegida registrada:", "SÍ" if stored_hash else "NO")
        if not stored_hash:
            return 1

        password = getpass.getpass("Escribe la contraseña del alta para comprobarla localmente: ")
        matches = verify_password(password, stored_hash)
        del password
        print("6. Contraseña coincide con el registro:", "SÍ" if matches else "NO")
        if matches and user.get("estado") == "ACTIVO":
            print("Coincide localmente. Si la API sigue devolviendo 401, investigar configuración de Lambda.")
        elif not matches:
            print("La contraseña ingresada no coincide con el hash almacenado. No se cambió ningún dato.")
        return 0

    except (ClientError, BotoCoreError) as exc:
        print("Error de AWS al consultar la tabla:", type(exc).__name__)
        if isinstance(exc, ClientError):
            print("Código AWS:", exc.response.get("Error", {}).get("Code", "desconocido"))
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado. Ejecútalo como archivo en la terminal EC2 interactiva.")
        sys.exit(1)
