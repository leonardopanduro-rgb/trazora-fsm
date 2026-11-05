"""Prueba interactiva MS4 ciclo de visitas; solo registros nuevos con SI.

Comprueba reprogramación/cancelación en un registro nuevo de prueba.
Puede opcionalmente iniciar una segunda visita, que quedará EN_ATENCION
para las pruebas posteriores de MS5 (sin cierre automático todavía).
"""
import sys
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from probar_ms4 import request, login, expect, api_url, MS0, MS2, LIMA


def iso_utc(fecha, hh, mm=0):
    local = datetime.combine(fecha, time(hh, mm), tzinfo=LIMA)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")


def main():
    print("=== MS4: iniciar, reprogramar y cancelar visita ===")
    ms4 = api_url(input("URL MS4 (terminada en /dev o /dev/visitas): "), "visitas")
    ms3 = api_url(os.getenv(
        "MS3_ORDENES_API_BASE",
        "https://ul25x5oe02.execute-api.us-east-1.amazonaws.com/dev",
    ), "ordenes")
    clima = login("CLIMALIMA", "admin-clima@example.com")
    if not clima:
        return 1
    frio = None
    ok = True
    try:
        frio = login("FRIOSUR", "admin-frio@example.com")
        if not frio:
            return 1
        code, data = request(ms3, "/ordenes?limit=50", token=clima)
        if code != 200:
            print("No se pueden listar órdenes:", code)
            return 1
        ordenes = [o for o in data.get("ordenes", [])
                   if o.get("estado") == "ABIERTA" and o.get("tenant_id") == "CLIMALIMA"]
        code, data = request(MS2, "/tecnicos?limit=50", token=clima)
        if code != 200:
            print("No se pueden listar técnicos:", code)
            return 1
        tecnicos = [t for t in data.get("tecnicos", [])
                    if t.get("activo") is True and t.get("tenant_id") == "CLIMALIMA"]
        pares = [(o, t) for o in ordenes for t in tecnicos
                 if o.get("tipo_servicio") in t.get("especialidades", [])]
        if not pares:
            print("No hay combinación orden ABIERTA + técnico activo compatible.")
            return 1
        orden, tecnico = pares[0]
        orden_id, tecnico_id = orden["orden_id"], tecnico["tecnico_id"]
        fecha = datetime.now(LIMA).date() + timedelta(days=16)
        fecha_str = fecha.isoformat()
        print("Orden de prueba:", orden_id)
        print("Técnico:", tecnico_id, "Fecha Lima:", fecha_str)
        code, data = request(
            MS2, f"/tecnicos/{tecnico_id}/jornadas?desde={fecha_str}&hasta={fecha_str}",
            token=clima,
        )
        if code != 200:
            print("No se pudo consultar la jornada:", code)
            return 1
        jornadas = data.get("jornadas", [])
        if jornadas:
            valido = any(
                any(i.get("inicio", "99:99") <= "09:00" and
                    i.get("fin", "00:00") >= "13:00"
                    for i in j.get("intervalos", []))
                for j in jornadas
            )
            if not valido:
                print("Hay una jornada existente que no cubre 09:00-13:00; no se sobrescribirá.")
                return 1
        else:
            if input("¿Crear jornada NUEVA 09:00-13:00 para ese día? Escribe SI: ") != "SI":
                print("Cancelado sin cambiar jornadas.")
                return 0
            code, _ = request(
                MS2, f"/tecnicos/{tecnico_id}/jornadas/{fecha_str}",
                "PUT", {"intervalos": [{"inicio": "09:00", "fin": "13:00"}]}, clima,
            )
            ok = expect("Crear jornada", code, 200) and ok
            if code != 200:
                return 1
        if input("¿Crear UNA visita de prueba, REPROGRAMARLA y CANCELARLA? Escribe SI: ") != "SI":
            print("No se creó ninguna visita.")
            return 0

        programar = {
            "orden_id": orden_id,
            "tecnico_id": tecnico_id,
            "inicio": iso_utc(fecha, 10),
            "fin": iso_utc(fecha, 11),
        }
        code, data = request(ms4, "/visitas", "POST", programar, clima)
        visit = data.get("visita", {}) if isinstance(data, dict) else {}
        visita_id = visit.get("visita_id")
        ok = expect("Programar visita de prueba", code, 201, bool(visita_id)) and ok
        if not visita_id:
            print("No se creó visita:", str(data.get("error", ""))[:160])
            return 1
        print("Visita de prueba:", visita_id)
        endpoint = f"/visitas/{visita_id}"
        try:
            nuevo = {
                "tecnico_id": tecnico_id,
                "inicio": iso_utc(fecha, 10, 30),
                "fin": iso_utc(fecha, 11, 30),
            }
            code, data = request(ms4, endpoint + "/reprogramar", "PATCH", nuevo, frio)
            ok = expect("FRIOSUR no puede reprogramar visita ajena", code, 404) and ok

            code, data = request(ms4, endpoint + "/reprogramar", "PATCH", nuevo, clima)
            visit = data.get("visita", {}) if isinstance(data, dict) else {}
            ok = expect(
                "Reprogramar visita", code, 200,
                visit.get("inicio") == nuevo["inicio"] and visit.get("version", 0) >= 2,
            ) and ok

            if code == 200:
                code, data = request(ms4, endpoint + "/reprogramar", "PATCH", nuevo, clima)
                ok = expect("Reprogramar repetida sin cambios", code, 200,
                            data.get("sin_cambios") is True) and ok
                code, data = request(ms4, endpoint, token=clima)
                ok = expect("Consultar horario actualizado", code, 200,
                            data.get("visita", {}).get("inicio") == nuevo["inicio"]) and ok
            code, data = request(ms4, endpoint + "/cancelar", "POST", {}, clima)
            ok = expect("Cancelar y liberar reservas", code, 200,
                        data.get("visita", {}).get("estado") == "CANCELADA") and ok
            if code != 200:
                print("ATENCION: la visita de prueba quedó PROGRAMADA. ID:", visita_id)
                return 1

            code, data = request(ms4, endpoint + "/cancelar", "POST", {}, clima)
            ok = expect("Cancelar repetida, sin contador duplicado", code, 200,
                        data.get("sin_cambios") is True) and ok
            code, data = request(ms4, endpoint + "/iniciar", "POST", {}, clima)
            ok = expect("Impedir iniciar visita cancelada", code, 409) and ok
        except Exception as exc:
            print("Error en las pruebas, visita a revisar:", visita_id, type(exc).__name__)
            raise

        if input("¿Crear otra visita y dejarla EN_ATENCION para pruebas MS5? Escribe SI: ").strip() == "SI":
            otra = dict(programar, inicio=iso_utc(fecha, 12), fin=iso_utc(fecha, 12, 30))
            code, data = request(ms4, "/visitas", "POST", otra, clima)
            visit = data.get("visita", {}) if isinstance(data, dict) else {}
            nueva_id = visit.get("visita_id")
            ok = expect("Programar segunda visita", code, 201, bool(nueva_id)) and ok
            if nueva_id:
                print("Visita para MS5:", nueva_id)
                code, data = request(ms4, f"/visitas/{nueva_id}/iniciar", "POST", {}, clima)
                ok = expect("Iniciar visita", code, 200,
                            data.get("visita", {}).get("estado") == "EN_ATENCION") and ok
                if code == 200:
                    code, data = request(ms4, f"/visitas/{nueva_id}/iniciar", "POST", {}, clima)
                    ok = expect("Reintento iniciar sin cambios", code, 200,
                                data.get("sin_cambios") is True) and ok
                print("Conserva el ID para MS5; aún no existe finalizar parte/eventos.")
        print("RESULTADO FINAL:", "TODAS LAS PRUEBAS PASARON" if ok else "REVISAR")
        return 0 if ok else 1
    finally:
        if clima:
            code, _ = request(MS0, "/auth/logout", "POST", {}, clima)
            print("Logout CLIMALIMA:", code)
        if frio:
            code, _ = request(MS0, "/auth/logout", "POST", {}, frio)
            print("Logout FRIOSUR:", code)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError, ValueError) as exc:
        print("Prueba detenida:", str(exc)[:180])
        sys.exit(1)
