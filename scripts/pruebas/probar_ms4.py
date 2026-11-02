"""Prueba MS4: programación, bloques reservados y separación entre tenants.

Requiere MS0, MS2 y MS3 desplegados en la misma cuenta/etapa.
Solicita confirmación antes de crear una jornada o una visita ficticia.
No imprime contraseñas ni tokens. Cierra las sesiones al final.
"""
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MS0 = "https://3yti33bqaf.execute-api.us-east-1.amazonaws.com/dev"
MS2 = "https://lil6er5i20.execute-api.us-east-1.amazonaws.com/dev"
LIMA = ZoneInfo("America/Lima")


def api_url(raw, endpoint):
    raw = raw.strip().rstrip("/")
    partes = urllib.parse.urlsplit(raw)
    if (partes.scheme != "https" or not partes.hostname
            or not partes.hostname.endswith(".execute-api.us-east-1.amazonaws.com")
            or partes.username or partes.password or partes.query or partes.fragment):
        raise ValueError("Debe ser URL HTTPS de API Gateway us-east-1.")
    path = partes.path
    if path.endswith("/" + endpoint):
        path = path[:-len(endpoint) - 1]
    if path != "/dev":
        raise ValueError("La URL debe terminar en /dev o /dev/" + endpoint)
    return "https://" + partes.hostname + "/dev"


def request(base, path, method="GET", data=None, token=None):
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            code, raw = res.status, res.read()
    except urllib.error.HTTPError as exc:
        code, raw = exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc.reason)[:130]}
    try:
        return code, json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return code, {"error": "Respuesta no JSON: revisar URL, permisos o logs de Lambda"}


def login(tenant, correo_por_defecto):
    email = input(f"Correo {tenant} [{correo_por_defecto}]: ").strip().lower()
    if not email:
        email = correo_por_defecto
    password = getpass.getpass(f"Contraseña de {tenant}: ")
    status, result = request(MS0, "/auth/login", "POST", {
        "tenant_id": tenant, "email": email, "password": password,
    })
    del password
    print(f"Login de {tenant}: HTTP {status} (esperado 200)")
    if status != 200 or not result.get("token"):
        print("Error:", str(result.get("error", "No se obtuvo token"))[:150])
        return None
    profile = result.get("usuario", {})
    if profile.get("tenant_id") != tenant or profile.get("rol") != "ADMIN":
        request(MS0, "/auth/logout", "POST", {}, result["token"])
        print("Se requiere ADMIN del tenant esperado.")
        return None
    return result["token"]


def expect(etiqueta, code, expected, predicate=True):
    ok = code == expected and predicate
    print(f"{etiqueta}: HTTP {code} (esperado {expected}) -> {'OK' if ok else 'REVISAR'}")
    return ok


def main():
    print("=== Trazora — Prueba de MS4 Agenda ===")
    ms4 = api_url(input("Pega URL MS4 (/dev o /dev/visitas): "), "visitas")
    ms3_input = os.getenv("MS3_ORDENES_API_BASE", "")
    if not ms3_input:
        ms3_input = input("Pega URL MS3 Ordenes (/dev o /dev/ordenes): ")
    ms3 = api_url(ms3_input, "ordenes")

    code, _ = request(ms4, "/visitas")
    aprobado = expect("Listar visitas sin token", code, 401)

    clima = login("CLIMALIMA", "admin-clima@example.com")
    if not clima:
        return 1
    frio = None
    try:
        frio = login("FRIOSUR", "admin-frio@example.com")
        if not frio:
            return 1

        code, body = request(ms3, "/ordenes?limit=50", token=clima)
        if code != 200:
            print("No se pudo listar órdenes de CLIMALIMA en MS3. HTTP", code)
            return 1
        ordenes = [
            x for x in body.get("ordenes", [])
            if x.get("tenant_id") == "CLIMALIMA" and x.get("estado") == "ABIERTA"
        ]
        if not ordenes:
            print("No se encontró una orden ABIERTA de CLIMALIMA. Ejecuta primero probar_ms3.py.")
            return 1

        code, body = request(MS2, "/tecnicos?limit=50", token=clima)
        if code != 200:
            print("No se pudo consultar técnicos de MS2. HTTP", code)
            return 1
        tecnicos = [
            x for x in body.get("tecnicos", [])
            if x.get("tenant_id") == "CLIMALIMA" and x.get("activo") is True
        ]
        candidatos = [(o, t) for o in ordenes for t in tecnicos
                      if o.get("tipo_servicio") in t.get("especialidades", [])]
        if not candidatos:
            print("No existe una combinación orden abierta + técnico con especialidad compatible.")
            print("Verifica el tipo de servicio en MS3 y especialidades en MS2.")
            return 1
        orden, tecnico = candidatos[0]
        orden_id, tecnico_id = orden["orden_id"], tecnico["tecnico_id"]
        print("Orden de CLIMALIMA:", orden_id)
        print("Técnico de CLIMALIMA:", tecnico_id)
        print("Especialidad:", orden["tipo_servicio"])

        # Día futuro elegido para no alterar la jornada usada en pruebas anteriores.
        fecha = (datetime.now(LIMA).date() + timedelta(days=14)).isoformat()
        code, body = request(
            MS2, f"/tecnicos/{tecnico_id}/jornadas?desde={fecha}&hasta={fecha}",
            token=clima,
        )
        if code != 200:
            print("No se pudo consultar jornada de MS2. HTTP", code)
            return 1
        jornadas = body.get("jornadas", [])
        if jornadas:
            print("Existe jornada para esa fecha; no se sobrescribirá.")
            print("La prueba continuará solo si cubre 10:00-11:00 de Lima.")
            valido = any(
                any(i.get("inicio", "99:99") <= "10:00"
                    and i.get("fin", "00:00") >= "11:00"
                    for i in jornada.get("intervalos", []))
                for jornada in jornadas
            )
            if not valido:
                print("La jornada existente no cubre el horario de demostración.")
                return 1
        else:
            print("No existe jornada de ese técnico el día", fecha)
            if input("¿Crear jornada ficticia de 09:00-12:00 Lima en MS2? Escribe SI: ").strip() != "SI":
                print("Cancelado sin modificar horarios.")
                return 0
            code, _ = request(
                MS2, f"/tecnicos/{tecnico_id}/jornadas/{fecha}", "PUT",
                {"intervalos": [{"inicio": "09:00", "fin": "12:00"}]}, clima,
            )
            if code != 200:
                print("No se pudo crear jornada. HTTP", code)
                return 1

        inicio_lima = datetime.combine(
            datetime.fromisoformat(fecha).date(), time(hour=10), tzinfo=LIMA
        )
        fin_lima = inicio_lima + timedelta(hours=1)
        inicio = inicio_lima.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        fin = fin_lima.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        print("Horario Lima: 10:00-11:00", fecha)
        if input("¿Programar UNA visita ficticia en MS4? Escribe SI: ").strip() != "SI":
            print("Cancelado sin crear visita.")
            return 0

        datos = {
            "orden_id": orden_id,
            "tecnico_id": tecnico_id,
            "inicio": inicio,
            "fin": fin,
        }
        code, body = request(ms4, "/visitas", "POST", datos, clima)
        visita = body.get("visita", {}) if isinstance(body, dict) else {}
        visita_id = visita.get("visita_id", "")
        aprobado = expect(
            "CLIMALIMA programa visita", code, 201,
            bool(visita_id) and visita.get("tenant_id") == "CLIMALIMA"
        ) and aprobado
        if not visita_id:
            print("Error:", str(body.get("error", "No se pudo crear visita"))[:180])
            return 1
        print("Visita de CLIMALIMA ID:", visita_id)

        code, body = request(ms4, "/visitas/" + visita_id, token=clima)
        v = body.get("visita", {}) if isinstance(body, dict) else {}
        aprobado = expect(
            "CLIMALIMA consulta su visita", code, 200,
            v.get("orden_id") == orden_id and v.get("tenant_id") == "CLIMALIMA"
        ) and aprobado

        code, body = request(ms4, "/visitas?limit=50", token=clima)
        visitas = body.get("visitas", []) if isinstance(body, dict) else []
        aprobado = expect(
            "CLIMALIMA lista sus visitas", code, 200,
            all(v.get("tenant_id") == "CLIMALIMA" for v in visitas)
        ) and aprobado

        code, _ = request(ms4, "/visitas/" + visita_id, token=frio)
        aprobado = expect("FRIOSUR consulta visita ajena", code, 404) and aprobado

        code, body = request(ms4, "/visitas?limit=50", token=frio)
        visitas = body.get("visitas", []) if isinstance(body, dict) else []
        aprobado = expect(
            "FRIOSUR no lista visitas de CLIMALIMA", code, 200,
            all(v.get("tenant_id") == "FRIOSUR" and v.get("visita_id") != visita_id
                for v in visitas)
        ) and aprobado

        code, _ = request(ms4, "/visitas", "POST", datos, clima)
        aprobado = expect("Se rechaza reserva de bloque duplicado", code, 409) and aprobado

        code, _ = request(ms4, "/visitas", "POST",
                          dict(datos, tenant_id="FRIOSUR"), clima)
        aprobado = expect("Se rechaza tenant_id forzado", code, 400) and aprobado

        print("RESULTADO FINAL:",
              "TODAS LAS PRUEBAS PASARON" if aprobado else "REVISAR PRUEBAS FALLIDAS")
        return 0 if aprobado else 1
    finally:
        if clima:
            code, _ = request(MS0, "/auth/logout", "POST", {}, clima)
            print("Logout CLIMALIMA: HTTP", code)
        if frio:
            code, _ = request(MS0, "/auth/logout", "POST", {}, frio)
            print("Logout FRIOSUR: HTTP", code)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError, ValueError) as exc:
        print("Prueba interrumpida:", str(exc)[:180])
        sys.exit(1)
