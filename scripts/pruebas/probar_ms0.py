"""Prueba interactiva de MS0 desde EC2, sin mostrar contraseñas ni tokens."""
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.getenv(
    "TRAZORA_MS0_URL",
    "https://3yti33bqaf.execute-api.us-east-1.amazonaws.com/dev",
).rstrip("/")


def request_json(path, method="GET", data=None, token=None):
    headers = {"Accept": "application/json"}
    payload = None
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        BASE + path, data=payload, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except urllib.error.URLError as exc:
        return 0, {"error": "No se pudo conectar con la API: " + str(exc.reason)}
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, {"error": "Respuesta no JSON (comprobar URL/API Gateway)."}


def main():
    print("Prueba de login de Trazora MS0 (las credenciales y el token NO se imprimirán)")
    print("API:", BASE)
    tenant = input("Empresa (CLIMALIMA/FRIOSUR): ").strip().upper()
    if tenant not in ("CLIMALIMA", "FRIOSUR"):
        print("Usa CLIMALIMA o FRIOSUR para esta prueba.")
        return 1
    email = input("Correo del administrador: ").strip().lower()
    password = getpass.getpass("Contraseña: ")

    status, login_data = request_json("/auth/login", "POST", {
        "tenant_id": tenant,
        "email": email,
        "password": password,
    })
    del password
    print("Login: HTTP", status)
    if status != 200 or not isinstance(login_data, dict) or not login_data.get("token"):
        error = login_data.get("error", "No se obtuvo token") if isinstance(login_data, dict) else "Respuesta inesperada"
        print("Error:", str(error)[:200])
        return 1

    token = login_data["token"]
    status, profile = request_json("/usuarios/me", token=token)
    print("Perfil: HTTP", status)
    if status == 200:
        print("Perfil:", json.dumps(profile, ensure_ascii=False))
    else:
        print("Error:", str(profile.get("error", "No se pudo consultar perfil"))[:200])

    status, result = request_json("/auth/logout", "POST", {}, token)
    print("Logout: HTTP", status)
    if status != 200:
        print("Error:", str(result.get("error", "No se pudo cerrar sesión"))[:200])

    status, _ = request_json("/usuarios/me", token=token)
    print("Consulta tras logout: HTTP", status, "(esperado: 401)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EOFError, KeyboardInterrupt):
        print("\nEjecución cancelada: utiliza una terminal interactiva.")
        sys.exit(1)
