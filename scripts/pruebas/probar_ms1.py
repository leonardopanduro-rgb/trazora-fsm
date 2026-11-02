"""Prueba de integración MS0->MS1 entre CLIMALIMA y FRIOSUR desde EC2.

Crea UN cliente ficticio en CLIMALIMA si el usuario confirma.
No imprime contraseñas ni tokens. No cambia código AWS ni crea recursos.
"""
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

AUTH_URL = os.getenv(
    "TRAZORA_MS0_URL", "https://3yti33bqaf.execute-api.us-east-1.amazonaws.com/dev"
).rstrip("/")


def normalizar_clientes_url(raw):
    raw = raw.strip().rstrip("/")
    parts = urllib.parse.urlsplit(raw)
    if (parts.scheme != "https" or
            not parts.hostname or
            not parts.hostname.endswith(".execute-api.us-east-1.amazonaws.com") or
            parts.query or parts.fragment):
        raise ValueError("URL inválida. Pega la URL HTTPS de API Gateway en us-east-1.")
    path = parts.path
    if path.endswith("/clientes"):
        path = path[:-len("/clientes")]
    if path != "/dev":
        raise ValueError("Se esperaba una ruta que termine en /dev o /dev/clientes.")
    return f"https://{parts.hostname}{path}"


def solicitar(base, path, method="GET", body=None, token=None):
    headers = {"Accept": "application/json"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        base + path, data=payload, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            code, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        code, raw = exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc.reason)[:100]}
    try:
        return code, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return code, {"error": "Respuesta no JSON: revisar URL, permisos o API Gateway"}


def entrar(tenant):
    correo_default = {
        "CLIMALIMA": "admin-clima@example.com",
        "FRIOSUR": "admin-frio@example.com",
    }[tenant]
    email = input(f"Correo {tenant} [{correo_default}]: ").strip().lower() or correo_default
    clave = getpass.getpass(f"Contraseña de {tenant}: ")
    code, body = solicitar(AUTH_URL, "/auth/login", "POST", {
        "tenant_id": tenant,
        "email": email,
        "password": clave,
    })
    del clave
    print(f"Login {tenant}: HTTP {code} (esperado: 200)")
    if code != 200 or not isinstance(body, dict) or not body.get("token"):
        print("No se pudo autenticar:", body.get("error", "Sin token"))
        return None
    usuario = body.get("usuario", {})
    if usuario.get("tenant_id") != tenant or usuario.get("rol") != "ADMIN":
        print("El perfil no corresponde al ADMIN solicitado. Prueba detenida.")
        return None
    return body["token"]


def verificar(etiqueta, status, esperado, condition=True):
    aprobado = status == esperado and condition
    print(f"{etiqueta}: HTTP {status} (esperado {esperado}) -> {'OK' if aprobado else 'REVISAR'}")
    return aprobado


def main():
    print("=== Pruebas MS1 Clientes (sin exponer tokens) ===")
    try:
        url = normalizar_clientes_url(
            input("Pega URL de MS1 (terminada en /dev o /dev/clientes): ")
        )
    except ValueError as exc:
        print("Error:", exc)
        return 1

    code, _ = solicitar(url, "/clientes")
    ok = verificar("Listado sin token", code, 401)

    clima = entrar("CLIMALIMA")
    if not clima:
        return 1
    frio = entrar("FRIOSUR")
    if not frio:
        return 1

    respuesta = input("¿Crear UN cliente ficticio de CLIMALIMA en DynamoDB? Escribe SI: ").strip()
    if respuesta != "SI":
        print("Cancelado antes de crear clientes.")
        return 0

    code, body = solicitar(url, "/clientes", "POST", {
        "nombre": "Cliente Demo de ClimaLima",
        "correo": "demo-clima@example.com",
        "telefono": "000000000",
    }, clima)
    cliente = body.get("cliente", {}) if isinstance(body, dict) else {}
    cliente_id = cliente.get("cliente_id", "")
    ok = verificar(
        "Crear cliente de CLIMALIMA", code, 201,
        cliente.get("tenant_id") == "CLIMALIMA" and bool(cliente_id)
    ) and ok
    if not cliente_id:
        print("No se creó el cliente. Error:", body.get("error", "Respuesta inesperada"))
        return 1
    print("ID de cliente de prueba:", cliente_id)

    code, body = solicitar(url, f"/clientes/{cliente_id}", token=clima)
    found = body.get("cliente", {}) if isinstance(body, dict) else {}
    ok = verificar("Consultar cliente con CLIMALIMA", code, 200,
                   found.get("tenant_id") == "CLIMALIMA") and ok

    code, body = solicitar(url, "/clientes?limit=50", token=clima)
    clientes = body.get("clientes", []) if isinstance(body, dict) else []
    ok = verificar("Listado de CLIMALIMA", code, 200,
                   any(c.get("cliente_id") == cliente_id for c in clientes)) and ok

    code, body = solicitar(url, f"/clientes/{cliente_id}", token=frio)
    ok = verificar("FRIOSUR intenta consultar el cliente ajeno", code, 404) and ok

    code, body = solicitar(url, "/clientes?limit=50", token=frio)
    clientes = body.get("clientes", []) if isinstance(body, dict) else []
    ok = verificar("Listado de FRIOSUR sin cliente ajeno", code, 200,
                   all(c.get("cliente_id") != cliente_id for c in clientes)) and ok

    code, _ = solicitar(url, "/clientes", "POST", {
        "nombre": "Intento de tenant ajeno", "tenant_id": "FRIOSUR",
    }, clima)
    ok = verificar("Body intenta cambiar tenant", code, 400) and ok
    print("Resultado global:", "TODAS LAS PRUEBAS PASARON" if ok else "REVISAR PRUEBAS FALLIDAS")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nPrueba interrumpida.")
        sys.exit(1)
