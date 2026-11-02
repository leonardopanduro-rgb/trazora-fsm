"""Pruebas de MS3 Órdenes con autenticación y aislamiento por tenant.

Requiere MS0 y MS1 existentes. Crea UNA orden de demostración si confirmas.
Nunca imprime contraseñas ni tokens. Revoca las sesiones al terminar.
"""
import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

MS0 = "https://3yti33bqaf.execute-api.us-east-1.amazonaws.com/dev"
MS1 = "https://9qksceoae2.execute-api.us-east-1.amazonaws.com/dev"


def normalizar_url(url):
    url = url.strip().rstrip("/")
    partes = urllib.parse.urlsplit(url)
    if (partes.scheme != "https" or not partes.hostname or
            not partes.hostname.endswith(".execute-api.us-east-1.amazonaws.com") or
            partes.username or partes.password or partes.query or partes.fragment):
        raise ValueError("La URL debe ser HTTPS de API Gateway us-east-1.")
    ruta = partes.path
    if ruta.endswith("/ordenes"):
        ruta = ruta[:-len("/ordenes")]
    if ruta != "/dev":
        raise ValueError("Debe terminar en /dev o /dev/ordenes.")
    return f"https://{partes.hostname}/dev"


def llamar(base, ruta, metodo="GET", json_body=None, token=None):
    headers = {"Accept": "application/json"}
    contenido = None
    if json_body is not None:
        contenido = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        base + ruta, data=contenido, headers=headers, method=metodo
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            status, data = res.status, res.read()
    except urllib.error.HTTPError as exc:
        status, data = exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, {"error": "Error de conexión: " + str(exc.reason)[:100]}
    try:
        return status, json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return status, {"error": "Respuesta no JSON; revisar API Gateway o CloudWatch"}


def iniciar(tenant, correo_predeterminado):
    correo = input(f"Correo {tenant} [{correo_predeterminado}]: ").strip().lower()
    if not correo:
        correo = correo_predeterminado
    clave = getpass.getpass(f"Contraseña de {tenant}: ")
    status, result = llamar(MS0, "/auth/login", "POST", {
        "tenant_id": tenant, "email": correo, "password": clave,
    })
    del clave
    print(f"Login {tenant}: HTTP {status} (esperado: 200)")
    if status != 200 or not isinstance(result, dict) or not result.get("token"):
        print("Error:", str(result.get("error", "No se recibió token"))[:150])
        return None
    usuario = result.get("usuario") or {}
    if usuario.get("tenant_id") != tenant or usuario.get("rol") != "ADMIN":
        print("No es el administrador esperado. Deteniendo prueba.")
        llamar(MS0, "/auth/logout", "POST", {}, result["token"])
        return None
    return result["token"]


def revisar(nombre, status, esperado, valido=True):
    correcto = status == esperado and valido
    print(f"{nombre}: HTTP {status} (esperado {esperado}) -> "
          + ("OK" if correcto else "REVISAR"))
    return correcto


def main():
    print("=== MS3 Órdenes — Prueba de aislamiento ===")
    ms3 = normalizar_url(input("URL de MS3 (terminada en /dev o /dev/ordenes): "))
    status, _ = llamar(ms3, "/ordenes")
    correcto = revisar("Sin token", status, 401)

    clima = iniciar("CLIMALIMA", "admin-clima@example.com")
    if not clima:
        return 1
    frio = None
    try:
        frio = iniciar("FRIOSUR", "admin-frio@example.com")
        if not frio:
            return 1

        status, body = llamar(MS1, "/clientes?limit=50", token=clima)
        if status != 200:
            print("No se pudo listar Clientes MS1 para CLIMALIMA:", status)
            return 1
        clientes = body.get("clientes", []) if isinstance(body, dict) else []
        disponibles = [c for c in clientes if c.get("tenant_id") == "CLIMALIMA"
                       and c.get("activo") is True and c.get("cliente_id")]
        if not disponibles:
            print("No hay cliente activo visible en MS1 para CLIMALIMA.")
            print("Ejecuta primero la prueba de MS1 Clientes.")
            return 1
        cliente_id = disponibles[0]["cliente_id"]
        print("Cliente existente de CLIMALIMA:", cliente_id)

        if input("¿Crear UNA orden ficticia en DynamoDB de CLIMALIMA? Escribe SI: ").strip() != "SI":
            print("Cancelado sin crear órdenes.")
            return 0

        body_orden = {
            "cliente_id": cliente_id,
            "tipo_servicio": "REPARACION",
            "descripcion": "Aire acondicionado de prueba no enfría correctamente",
            "prioridad": "ALTA",
        }
        status, body = llamar(ms3, "/ordenes", "POST", body_orden, clima)
        orden = body.get("orden", {}) if isinstance(body, dict) else {}
        orden_id = orden.get("orden_id")
        correcto = revisar("CLIMALIMA crea orden", status, 201,
                           orden.get("tenant_id") == "CLIMALIMA" and bool(orden_id)) and correcto
        if not orden_id:
            print("Error:", str(body.get("error", "No se creó la orden"))[:150])
            return 1
        print("ID de orden de prueba:", orden_id)

        status, body = llamar(ms3, "/ordenes/" + orden_id, token=clima)
        orden = body.get("orden", {}) if isinstance(body, dict) else {}
        correcto = revisar("CLIMALIMA consulta su orden", status, 200,
                           orden.get("tenant_id") == "CLIMALIMA" and
                           orden.get("cliente_id") == cliente_id) and correcto

        status, body = llamar(ms3, "/ordenes?limit=50", token=clima)
        ordenes = body.get("ordenes", []) if isinstance(body, dict) else []
        correcto = revisar("CLIMALIMA lista sus órdenes", status, 200,
                           all(o.get("tenant_id") == "CLIMALIMA" for o in ordenes)) and correcto

        status, _ = llamar(ms3, "/ordenes/" + orden_id, token=frio)
        correcto = revisar("FRIOSUR intenta leer orden ajena", status, 404) and correcto

        status, body = llamar(ms3, "/ordenes?limit=50", token=frio)
        ordenes = body.get("ordenes", []) if isinstance(body, dict) else []
        correcto = revisar("FRIOSUR lista solo sus órdenes", status, 200,
                           all(o.get("tenant_id") == "FRIOSUR" and
                               o.get("orden_id") != orden_id for o in ordenes)) and correcto

        status, _ = llamar(ms3, "/ordenes", "POST",
                           dict(body_orden, tenant_id="FRIOSUR"), clima)
        correcto = revisar("Rechazar tenant_id inyectado", status, 400) and correcto

        status, _ = llamar(ms3, "/ordenes", "POST", body_orden, frio)
        correcto = revisar("FRIOSUR no usa cliente ajeno", status, 404) and correcto

        print("RESULTADO FINAL:",
              "TODAS LAS PRUEBAS PASARON" if correcto else "REVISAR PRUEBAS FALLIDAS")
        return 0 if correcto else 1
    finally:
        if clima:
            status, _ = llamar(MS0, "/auth/logout", "POST", {}, clima)
            print("Logout CLIMALIMA:", status)
        if frio:
            status, _ = llamar(MS0, "/auth/logout", "POST", {}, frio)
            print("Logout FRIOSUR:", status)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError, ValueError) as exc:
        print("Prueba interrumpida:", str(exc)[:160])
        sys.exit(1)
