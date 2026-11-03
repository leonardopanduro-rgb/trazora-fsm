"""Prueba interactiva MS5 Partes: borrador, aislamiento y evidencia S3 privada.

Requiere MS0, MS4 y MS5 desplegados en us-east-1 dev.
No imprime contraseñas, tokens ni URLs prefirmadas S3.
"""
import base64
import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

MS0 = "https://3yti33bqaf.execute-api.us-east-1.amazonaws.com/dev"
MS4 = "https://4o2ucd2ati.execute-api.us-east-1.amazonaws.com/dev"
PNG_DEMO = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9fSE8c8AAAAASUVORK5CYII="
)


def url_base(raw, endpoint):
    parts = urllib.parse.urlsplit(raw.strip().rstrip("/"))
    if (parts.scheme != "https" or not parts.hostname or
            not parts.hostname.endswith(".execute-api.us-east-1.amazonaws.com") or
            parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("Pega una URL HTTPS de API Gateway en us-east-1")
    path = parts.path
    if path.endswith("/" + endpoint):
        path = path[:-len(endpoint) - 1]
    if path != "/dev":
        raise ValueError("La URL debe terminar en /dev o /dev/" + endpoint)
    return "https://" + parts.hostname + "/dev"


def pedir(base, path, method="GET", body=None, token=None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=25) as res:
            status, raw = res.status, res.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, {"error": "Error de conexión: " + str(exc.reason)[:120]}
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return status, {"error": "Respuesta no JSON (revisar API/CloudWatch)"}


def login(tenant, email_default):
    email = input(f"Correo {tenant} [{email_default}]: ").strip().lower() or email_default
    password = getpass.getpass("Contraseña de " + tenant + ": ")
    code, data = pedir(MS0, "/auth/login", "POST", {
        "tenant_id": tenant, "email": email, "password": password,
    })
    del password
    print(f"Login {tenant}: HTTP {code} (esperado 200)")
    if code != 200 or not data.get("token"):
        print("Error:", str(data.get("error", "No se obtuvo token"))[:180])
        return None
    if data.get("usuario", {}).get("tenant_id") != tenant:
        pedir(MS0, "/auth/logout", "POST", {}, data["token"])
        print("El usuario pertenece a otra empresa")
        return None
    return data["token"]


def comprobar(texto, code, esperado, extra=True):
    ok = code == esperado and extra
    print(f"{texto}: HTTP {code} (esperado {esperado}) -> {'OK' if ok else 'REVISAR'}")
    return ok


def formulario_s3(formulario):
    """Envía un PNG ficticio diminuto a S3 mediante POST multipart firmado."""
    upload_url = formulario.get("url")
    campos = formulario.get("fields")
    if not isinstance(upload_url, str) or not isinstance(campos, dict):
        raise ValueError("No se recibió un formulario S3 válido")
    boundary = "----Trazora" + uuid.uuid4().hex
    pieces = []
    for name, value in campos.items():
        pieces.append(("--" + boundary + "\r\n").encode())
        pieces.append(
            ('Content-Disposition: form-data; name="' + str(name) + '"\r\n\r\n').encode()
        )
        pieces.append(str(value).encode() + b"\r\n")
    pieces.append(("--" + boundary + "\r\n").encode())
    pieces.append(
        b'Content-Disposition: form-data; name="file"; filename="demo.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
    )
    pieces.append(PNG_DEMO + b"\r\n")
    pieces.append(("--" + boundary + "--\r\n").encode())
    data = b"".join(pieces)
    request = urllib.request.Request(
        upload_url,
        data=data,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as res:
            return res.status
    except urllib.error.HTTPError as exc:
        # No imprimir XML de AWS (puede contener identificadores y metadatos).
        return exc.code
    except urllib.error.URLError:
        return 0


def main():
    print("=== Trazora — Pruebas MS5 Partes y evidencias ===")
    ms5 = url_base(input("Pega la URL MS5 (terminada en /dev o /dev/partes): "), "partes")
    code, _ = pedir(ms5, "/partes/00000000-0000-0000-0000-000000000000")
    ok = comprobar("Consulta sin token", code, 401)

    clima = login("CLIMALIMA", "admin-clima@example.com")
    if not clima:
        return 1
    frio = None
    try:
        frio = login("FRIOSUR", "admin-frio@example.com")
        if not frio:
            return 1

        code, data = pedir(MS4, "/visitas?limit=50", token=clima)
        if code != 200:
            print("No se pudieron consultar visitas en MS4. HTTP", code)
            return 1
        visitas = [v for v in data.get("visitas", [])
                  if v.get("tenant_id") == "CLIMALIMA" and
                  v.get("estado") in ("PROGRAMADA", "EN_ATENCION")]
        if not visitas:
            print("No hay visitas PROGRAMADAS. Ejecuta primero probar_ms4.py.")
            return 1
        visita_id = visitas[0]["visita_id"]
        print("Visita de CLIMALIMA:", visita_id)

        code, data = pedir(ms5, f"/visitas/{visita_id}/partes", token=clima)
        if code == 404:
            if input("¿Crear UN borrador de parte para esta visita? Escribe SI: ").strip() != "SI":
                print("Cancelado; no se crearon datos.")
                return 0
            code, data = pedir(ms5, f"/visitas/{visita_id}/partes", "POST", {}, clima)
            ok = comprobar("Crear parte", code, 201) and ok
        else:
            ok = comprobar("Recuperar parte existente", code, 200) and ok
        parte = data.get("parte", {}) if isinstance(data, dict) else {}
        parte_id = parte.get("parte_id")
        if not parte_id:
            print("No se obtuvo ID de parte:", str(data.get("error", ""))[:180])
            return 1
        print("ID de parte:", parte_id)

        code, data = pedir(ms5, "/partes/" + parte_id, token=clima)
        part = data.get("parte", {}) if isinstance(data, dict) else {}
        ok = comprobar("CLIMALIMA consulta parte", code, 200,
                       part.get("tenant_id") == "CLIMALIMA") and ok

        code, _ = pedir(ms5, "/partes/" + parte_id, token=frio)
        ok = comprobar("FRIOSUR consulta parte ajeno", code, 404) and ok

        code, _ = pedir(ms5, f"/visitas/{visita_id}/partes", "POST",
                        {"tenant_id": "FRIOSUR"}, clima)
        ok = comprobar("Intento de tenant_id forzado", code, 400) and ok

        version = part.get("version")
        if isinstance(version, int):
            update = {
                "diagnostico": "Filtro de aire obstruido (prueba)",
                "tareas": ["Limpieza de filtro", "Prueba de enfriamiento"],
                "resultado": "RESUELTO",
                "version": version,
            }
            code, data = pedir(ms5, "/partes/" + parte_id, "PATCH", update, clima)
            nuevo = data.get("parte", {}) if isinstance(data, dict) else {}
            ok = comprobar("Editar borrador", code, 200,
                           nuevo.get("version") == version + 1) and ok
            code, _ = pedir(ms5, "/partes/" + parte_id, "PATCH", update, clima)
            ok = comprobar("Rechazar edición con versión antigua", code, 409) and ok

        if input("¿Subir una imagen PNG ficticia de 1 píxel a S3? Escribe SI: ").strip() != "SI":
            print("Se omite la prueba de S3.")
            return 0 if ok else 1

        code, data = pedir(ms5, f"/partes/{parte_id}/evidencias", "POST",
                           {"content_type": "image/png"}, clima)
        evidence = data.get("evidencia", {}) if isinstance(data, dict) else {}
        evidencia_id = evidence.get("evidencia_id")
        ok = comprobar("Preparar evidencia S3", code, 201, bool(evidencia_id)) and ok
        if not evidencia_id:
            print("No se obtuvo evidencia:", str(data.get("error", ""))[:180])
            return 1
        try:
            status_s3 = formulario_s3(data["upload"])
        except (ValueError, KeyError) as exc:
            print("No se pudo construir el formulario S3:", str(exc)[:120])
            return 1
        ok = comprobar("Subir PNG directamente a S3", status_s3, 204) and ok
        if status_s3 != 204:
            print("Revisa permisos de S3 o configuración del bucket, sin compartir el formulario firmado.")
            return 1
        code, data = pedir(
            ms5, f"/partes/{parte_id}/evidencias/{evidencia_id}/confirmar",
            "POST", {}, clima,
        )
        e = data.get("evidencia", {}) if isinstance(data, dict) else {}
        ok = comprobar("Confirmar archivo", code, 200, e.get("estado") == "CONFIRMADA") and ok

        code, data = pedir(
            ms5, f"/partes/{parte_id}/evidencias/{evidencia_id}/descargar",
            token=clima,
        )
        ok = comprobar("Conseguir enlace privado de lectura", code, 200,
                       bool(data.get("url"))) and ok
        code, _ = pedir(
            ms5, f"/partes/{parte_id}/evidencias/{evidencia_id}/descargar",
            token=frio,
        )
        ok = comprobar("FRIOSUR no accede a evidencia", code, 404) and ok

        print("RESULTADO FINAL:",
              "TODAS LAS PRUEBAS PASARON" if ok else "REVISAR PRUEBAS FALLIDAS")
        return 0 if ok else 1
    finally:
        if clima:
            code, _ = pedir(MS0, "/auth/logout", "POST", {}, clima)
            print("Logout CLIMALIMA: HTTP", code)
        if frio:
            code, _ = pedir(MS0, "/auth/logout", "POST", {}, frio)
            print("Logout FRIOSUR: HTTP", code)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError, ValueError) as exc:
        print("\nPrueba interrumpida:", str(exc)[:180])
        sys.exit(1)
