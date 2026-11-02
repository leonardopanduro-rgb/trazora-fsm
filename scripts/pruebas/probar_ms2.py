"""Pruebas de integración MS2: autenticación y aislamiento entre empresas.

Pide las contraseñas sin mostrarlas y revoca sesiones nuevas al finalizar.
Crea técnicos de demostración SOLO tras confirmar expresamente SI.
"""
import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

MS0 = "https://3yti33bqaf.execute-api.us-east-1.amazonaws.com/dev"


def url_ms2(raw):
    url = raw.strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or
            not parts.hostname.endswith(".execute-api.us-east-1.amazonaws.com") or
            parts.query or parts.fragment or parts.username or parts.password):
        raise ValueError("Ingresa la URL HTTPS de MS2 en us-east-1.")
    path = parts.path
    if path.endswith("/tecnicos"):
        path = path[:-len("/tecnicos")]
    if path != "/dev":
        raise ValueError("La URL debe terminar en /dev o /dev/tecnicos.")
    return "https://" + parts.hostname + path


def llamada(base, path, metodo="GET", datos=None, token=None):
    headers = {"Accept": "application/json"}
    body = None
    if datos is not None:
        body = json.dumps(datos).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=body, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status, result = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, result = exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc.reason)[:150]}
    try:
        return status, json.loads(result.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return status, {"error": "Respuesta no JSON. Revisar URL, Lambda y API Gateway."}


def login(tenant, default_email):
    email = input(f"Correo {tenant} [{default_email}]: ").strip().lower() or default_email
    password = getpass.getpass(f"Contraseña de {tenant}: ")
    status, result = llamada(MS0, "/auth/login", "POST", {
        "tenant_id": tenant, "email": email, "password": password,
    })
    del password
    print(f"Login de {tenant}: HTTP {status} (esperado 200)")
    if status != 200 or not isinstance(result, dict) or not result.get("token"):
        print("Error de autenticación:", result.get("error", "Sin token"))
        return None
    profile = result.get("usuario", {})
    if profile.get("tenant_id") != tenant or profile.get("rol") != "ADMIN":
        print("La cuenta no corresponde al administrador indicado.")
        llamada(MS0, "/auth/logout", "POST", {}, result["token"])
        return None
    return result["token"]


def comprobar(nombre, status, esperado, condicion=True):
    ok = status == esperado and condicion
    print(f"{nombre}: HTTP {status} (esperado {esperado}) -> {'OK' if ok else 'REVISAR'}")
    return ok


def main():
    print("=== Trazora: prueba MS2 Técnicos ===")
    url = url_ms2(input("URL MS2 (terminada en /dev o /dev/tecnicos): "))
    code, _ = llamada(url, "/tecnicos")
    todo_bien = comprobar("Sin token", code, 401)

    clima = login("CLIMALIMA", "admin-clima@example.com")
    if not clima:
        return 1
    frio = None
    try:
        frio = login("FRIOSUR", "admin-frio@example.com")
        if not frio:
            return 1

        confirmar = input("¿Crear 2 técnicos ficticios y 1 jornada en dev? Escribe SI: ").strip()
        if confirmar != "SI":
            print("Prueba cancelada sin crear datos.")
            return 0

        code, result = llamada(url, "/tecnicos", "POST", {
            "nombre": "Carlos Demo ClimaLima",
            "especialidades": ["REPARACION", "MANTENIMIENTO"],
        }, clima)
        cl = result.get("tecnico", {}) if isinstance(result, dict) else {}
        tecnico_cl = cl.get("tecnico_id")
        todo_bien = comprobar(
            "CLIMALIMA crea técnico", code, 201,
            cl.get("tenant_id") == "CLIMALIMA" and bool(tecnico_cl)
        ) and todo_bien
        if not tecnico_cl:
            print("Error de creación:", result.get("error", "Consultar logs de Lambda"))
            return 1
        print("Técnico CLIMALIMA ID:", tecnico_cl)

        code, result = llamada(url, "/tecnicos", "POST", {
            "nombre": "María Demo FríoSur", "especialidades": ["INSTALACION"],
        }, frio)
        fr = result.get("tecnico", {}) if isinstance(result, dict) else {}
        tecnico_fr = fr.get("tecnico_id")
        todo_bien = comprobar(
            "FRIOSUR crea técnico", code, 201,
            fr.get("tenant_id") == "FRIOSUR" and bool(tecnico_fr)
        ) and todo_bien
        if not tecnico_fr:
            print("Error de creación:", result.get("error", "Consultar logs de Lambda"))
            return 1

        code, result = llamada(url, f"/tecnicos/{tecnico_cl}", token=clima)
        t = result.get("tecnico", {}) if isinstance(result, dict) else {}
        todo_bien = comprobar("CLIMALIMA consulta propio técnico", code, 200,
                              t.get("tenant_id") == "CLIMALIMA") and todo_bien

        code, result = llamada(url, f"/tecnicos/{tecnico_cl}", token=frio)
        todo_bien = comprobar("FRIOSUR consulta ID ajeno", code, 404) and todo_bien

        code, result = llamada(url, "/tecnicos?limit=50", token=frio)
        items = result.get("tecnicos", []) if isinstance(result, dict) else []
        todo_bien = comprobar("FRIOSUR lista solo sus técnicos", code, 200,
                              any(x.get("tecnico_id") == tecnico_fr for x in items) and
                              all(x.get("tecnico_id") != tecnico_cl for x in items)) and todo_bien

        fecha = (date.today() + timedelta(days=1)).isoformat()
        jornada = {"intervalos": [
            {"inicio": "08:00", "fin": "12:00"},
            {"inicio": "13:00", "fin": "17:00"},
        ]}
        code, result = llamada(url, f"/tecnicos/{tecnico_cl}/jornadas/{fecha}", "PUT",
                               jornada, clima)
        item = result.get("jornada", {}) if isinstance(result, dict) else {}
        todo_bien = comprobar("CLIMALIMA guarda jornada", code, 200,
                              item.get("fecha") == fecha and
                              item.get("tenant_id") == "CLIMALIMA") and todo_bien

        q = f"?desde={fecha}&hasta={fecha}"
        code, result = llamada(url, f"/tecnicos/{tecnico_cl}/jornadas{q}", token=clima)
        jornadas = result.get("jornadas", []) if isinstance(result, dict) else []
        todo_bien = comprobar("CLIMALIMA consulta jornada", code, 200,
                              any(x.get("fecha") == fecha for x in jornadas)) and todo_bien

        code, _ = llamada(url, f"/tecnicos/{tecnico_cl}/jornadas{q}", token=frio)
        todo_bien = comprobar("FRIOSUR no consulta jornada ajena", code, 404) and todo_bien

        code, _ = llamada(url, "/tecnicos", "POST", {
            "nombre": "Intento forzado", "especialidades": ["REPARACION"],
            "tenant_id": "FRIOSUR",
        }, clima)
        todo_bien = comprobar("Rechazo de tenant_id inyectado", code, 400) and todo_bien

        print("RESULTADO FINAL:", "TODAS LAS PRUEBAS PASARON" if todo_bien else "REVISAR FALLAS")
        return 0 if todo_bien else 1
    finally:
        if clima:
            status, _ = llamada(MS0, "/auth/logout", "POST", {}, clima)
            print(f"Logout CLIMALIMA: HTTP {status} (esperado 200)")
        if frio:
            status, _ = llamada(MS0, "/auth/logout", "POST", {}, frio)
            print(f"Logout FRIOSUR: HTTP {status} (esperado 200)")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError, ValueError) as exc:
        print("\nSe interrumpió la prueba:", str(exc)[:180])
        sys.exit(1)
