"""Prueba interactiva y aislada de activar/desactivar técnico de MS2.

Usa administradores de CLIMALIMA y FRIOSUR. Crea SOLO UN técnico ficticio
en CLIMALIMA tras confirmación SI; no modifica técnicos existentes.
"""
import sys
from datetime import date, timedelta

from probar_ms2 import comprobar, llamada, login, url_ms2, MS0


def main():
    print("=== MS2: cambiar estado activo (ADMIN, multitenancy, Agenda) ===")
    ms2 = url_ms2(input("Pega la URL MS2 terminada en /dev o /dev/tecnicos: "))
    clima = login("CLIMALIMA", "admin-clima@example.com")
    if not clima:
        return 1
    frio = None
    ok = True
    try:
        frio = login("FRIOSUR", "admin-frio@example.com")
        if not frio:
            return 1
        if input("¿Crear UN técnico nuevo de prueba en CLIMALIMA? Escribe SI: ").strip() != "SI":
            print("Cancelado. No se crearon ni modificaron técnicos.")
            return 0

        code, data = llamada(ms2, "/tecnicos", "POST", {
            "nombre": "Técnico para prueba de estado",
            "especialidades": ["MANTENIMIENTO"],
        }, clima)
        tecnico = data.get("tecnico", {}) if isinstance(data, dict) else {}
        tecnico_id = tecnico.get("tecnico_id")
        ok = comprobar("Crear técnico activo", code, 201,
                       tecnico.get("activo") is True and bool(tecnico_id)) and ok
        if not tecnico_id:
            print("No se creó el técnico:", str(data.get("error", ""))[:180])
            return 1
        print("Técnico de prueba:", tecnico_id)

        endpoint = "/tecnicos/" + tecnico_id + "/estado"
        code, _ = llamada(ms2, endpoint, "PATCH", {"activo": False})
        ok = comprobar("Cambiar estado sin token", code, 401) and ok

        code, _ = llamada(ms2, endpoint, "PATCH", {"activo": False}, frio)
        ok = comprobar("No desactivar técnico de otra empresa", code, 404) and ok

        code, _ = llamada(ms2, endpoint, "PATCH", {
            "activo": False, "tenant_id": "FRIOSUR",
        }, clima)
        ok = comprobar("Rechazar tenant_id inyectado", code, 400) and ok

        code, _ = llamada(ms2, endpoint, "PATCH", {"activo": "false"}, clima)
        ok = comprobar("Rechazar activo no booleano", code, 400) and ok

        code, data = llamada(ms2, endpoint, "PATCH", {"activo": False}, clima)
        tecnico = data.get("tecnico", {}) if isinstance(data, dict) else {}
        ok = comprobar("Desactivar técnico sin reservas", code, 200,
                       tecnico.get("activo") is False) and ok
        if code != 200:
            print("Respuesta:", str(data.get("error", ""))[:180])
            print("Asegúrate de desplegar primero MS4 con el endpoint de reservas.")
            return 1

        code, data = llamada(ms2, "/tecnicos/" + tecnico_id, token=clima)
        tecnico = data.get("tecnico", {}) if isinstance(data, dict) else {}
        ok = comprobar("Consultar estado inactivo", code, 200,
                       tecnico.get("activo") is False) and ok

        fecha = (date.today() + timedelta(days=2)).isoformat()
        code, _ = llamada(
            ms2, f"/tecnicos/{tecnico_id}/jornadas/{fecha}", "PUT",
            {"intervalos": [{"inicio": "09:00", "fin": "12:00"}]}, clima,
        )
        ok = comprobar("Bloquear jornada estando inactivo", code, 409) and ok

        code, data = llamada(ms2, endpoint, "PATCH", {"activo": True}, clima)
        tecnico = data.get("tecnico", {}) if isinstance(data, dict) else {}
        ok = comprobar("Reactivar técnico", code, 200,
                       tecnico.get("activo") is True) and ok

        code, data = llamada(ms2, endpoint, "PATCH", {"activo": True}, clima)
        ok = comprobar("Reactivación repetida sin efectos secundarios", code, 200,
                       data.get("sin_cambios") is True) and ok

        code, _ = llamada(
            ms2, f"/tecnicos/{tecnico_id}/jornadas/{fecha}", "PUT",
            {"intervalos": [{"inicio": "09:00", "fin": "12:00"}]}, clima,
        )
        ok = comprobar("Registrar jornada tras reactivar", code, 200) and ok

        print("RESULTADO FINAL:",
              "TODAS LAS PRUEBAS PASARON" if ok else "REVISAR PRUEBAS FALLIDAS")
        return 0 if ok else 1
    finally:
        if clima:
            code, _ = llamada(MS0, "/auth/logout", "POST", {}, clima)
            print("Logout CLIMALIMA: HTTP", code)
        if frio:
            code, _ = llamada(MS0, "/auth/logout", "POST", {}, frio)
            print("Logout FRIOSUR: HTTP", code)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError, ValueError) as exc:
        print("Prueba interrumpida:", str(exc)[:180])
        sys.exit(1)
