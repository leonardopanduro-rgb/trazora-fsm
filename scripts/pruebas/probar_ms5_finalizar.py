"""Verifica la finalización de un parte ficticio de MS5 (crea datos solo con permiso).

En esta etapa el OUTBOX queda pendiente; MS4/MS3 no se actualizan por SQS.
"""
import sys

from probar_ms5 import (
    MS0, MS4, pedir, login, comprobar, url_base, formulario_s3,
)


def main():
    print("=== Trazora MS5: FINALIZAR parte + OUTBOX ===")
    ms5 = url_base(input("URL MS5 terminada en /dev o /dev/partes: "), "partes")
    clima = login("CLIMALIMA", "admin-clima@example.com")
    if not clima:
        return 1
    frio = None
    ok = True
    try:
        frio = login("FRIOSUR", "admin-frio@example.com")
        if not frio:
            return 1

        code, result = pedir(MS4, "/visitas?limit=50", token=clima)
        if code != 200:
            print("Error consultando MS4:", code)
            return 1
        visitas = [
            v for v in result.get("visitas", [])
            if v.get("tenant_id") == "CLIMALIMA" and
            v.get("estado") == "EN_ATENCION"
        ]
        if not visitas:
            print("No hay visita EN_ATENCION entre las primeras 50 de CLIMALIMA.")
            print("Ejecuta scripts/pruebas/probar_ms4_ciclo.py y responde SI")
            print("a la última pregunta para crear/iniciar una visita ficticia.")
            return 1

        print("Visitas EN_ATENCION disponibles:")
        for v in visitas[:10]:
            print("-", v.get("visita_id"), "orden:", v.get("orden_id"))
        visita_id = input(
            "Copia el UUID de UNA visita ficticia EN_ATENCION: "
        ).strip().lower()
        if visita_id not in {v["visita_id"] for v in visitas}:
            print("ID no reconocido en esta lista.")
            return 1

        code, data = pedir(ms5, f"/visitas/{visita_id}/partes", token=clima)
        if code == 404:
            if input("¿Crear borrador para esa visita? Escribe SI: ").strip() != "SI":
                print("No se crearon datos.")
                return 0
            code, data = pedir(
                ms5, f"/visitas/{visita_id}/partes", "POST", {}, clima
            )
            ok = comprobar("Crear borrador de parte", code, 201) and ok
        else:
            ok = comprobar("Recuperar parte", code, 200) and ok
        parte = data.get("parte", {}) if isinstance(data, dict) else {}
        parte_id = parte.get("parte_id")
        if not parte_id:
            print("No existe parte válido:", str(data.get("error", ""))[:150])
            return 1
        print("Parte de prueba:", parte_id)

        code, result = pedir(ms5, "/partes/" + parte_id, token=clima)
        ok = comprobar("Consultar borrador y evidencias", code, 200) and ok
        if code != 200:
            return 1
        parte = result["parte"]
        evidencias = result.get("evidencias", [])
        if parte.get("estado") == "FINALIZADO":
            print("Parte ya finalizado. No se escribirá otro evento.")
            return 0
        if parte.get("estado") != "BORRADOR":
            print("El parte no está en BORRADOR; operación cancelada.")
            return 1

        if (not parte.get("diagnostico") or not parte.get("tareas")
                or parte.get("resultado") == "PENDIENTE"):
            if input("¿Guardar diagnóstico ficticio y tareas? Escribe SI: ").strip() != "SI":
                print("El parte no está listo para finalizar.")
                return 0
            code, result = pedir(
                ms5, "/partes/" + parte_id, "PATCH", {
                    "diagnostico": "Limpieza de filtro completada (prueba académica)",
                    "tareas": ["Limpiar filtro", "Verificar enfriamiento"],
                    "resultado": "RESUELTO",
                    "version": parte["version"],
                }, clima,
            )
            ok = comprobar("Editar parte", code, 200) and ok
            if code != 200:
                return 1
            parte = result["parte"]

        confirmada = next(
            (e for e in evidencias if e.get("estado") == "CONFIRMADA"), None
        )
        if not confirmada:
            if input("¿Subir 1 PNG ficticio y confirmarlo? Escribe SI: ").strip() != "SI":
                print("Sin evidencia confirmada, el parte no se puede finalizar.")
                return 0
            code, result = pedir(
                ms5, "/partes/" + parte_id + "/evidencias",
                "POST", {"content_type": "image/png"}, clima,
            )
            ok = comprobar("Preparar evidencia", code, 201) and ok
            if code != 201:
                return 1
            evidencia_id = result["evidencia"]["evidencia_id"]
            status_s3 = formulario_s3(result["upload"])
            ok = comprobar("Subir PNG a S3", status_s3, 204) and ok
            if status_s3 != 204:
                return 1
            code, result = pedir(
                ms5,
                f"/partes/{parte_id}/evidencias/{evidencia_id}/confirmar",
                "POST", {}, clima,
            )
            ok = comprobar("Confirmar evidencia", code, 200) and ok
            if code != 200:
                return 1

        code, result = pedir(ms5, "/partes/" + parte_id, token=clima)
        if code != 200:
            return 1
        version = result["parte"]["version"]

        code, _ = pedir(
            ms5, "/partes/" + parte_id + "/finalizar",
            "POST", {"version": version}, frio,
        )
        ok = comprobar("FRIOSUR no finaliza parte ajeno", code, 404) and ok
        code, _ = pedir(
            ms5, "/partes/" + parte_id + "/finalizar",
            "POST", {"version": "invalido"}, clima,
        )
        ok = comprobar("Rechazar versión inválida", code, 400) and ok

        print("ATENCIÓN: finalizar NO se puede deshacer con esta API.")
        print("MS4 quedará EN_ATENCION hasta que implementemos SNS/SQS.")
        if input("Para finalizar este parte ficticio, escribe FINALIZAR: ").strip() != "FINALIZAR":
            print("Se omite la finalización; el borrador quedó guardado.")
            return 0 if ok else 1

        endpoint = "/partes/" + parte_id + "/finalizar"
        code, result = pedir(ms5, endpoint, "POST", {"version": version}, clima)
        parte = result.get("parte", {}) if isinstance(result, dict) else {}
        evento = result.get("evento", {}) if isinstance(result, dict) else {}
        ok = comprobar(
            "Finalizar parte y registrar OUTBOX", code, 200,
            parte.get("estado") == "FINALIZADO" and
            evento.get("event_type") == "ParteFinalizado" and
            evento.get("estado") in ("PENDIENTE_PUBLICACION", "PUBLICADO") and
            bool(evento.get("event_id")),
        ) and ok
        if code != 200:
            print("Error:", str(result.get("error", ""))[:180])
            return 1
        print("ID evento OUTBOX:", evento["event_id"])

        code, result = pedir(ms5, endpoint, "POST", {"version": version}, clima)
        ok = comprobar(
            "Reintento idempotente", code, 200,
            result.get("sin_cambios") is True and
            result.get("evento", {}).get("event_id") == evento["event_id"],
        ) and ok

        code, result = pedir(ms5, "/partes/" + parte_id, token=clima)
        ok = comprobar(
            "Parte persistido FINALIZADO", code, 200,
            result.get("parte", {}).get("estado") == "FINALIZADO",
        ) and ok

        code, result = pedir(MS4, "/visitas/" + visita_id, token=clima)
        if code == 200:
            print("Estado MS4 actual:", result.get("visita", {}).get("estado"),
                  "(EN_ATENCION si el consumidor esta deshabilitado; FINALIZADA despues de procesar SQS)")
        print("RESULTADO FINAL:",
              "TODAS LAS PRUEBAS PASARON" if ok else "REVISAR")
        return 0 if ok else 1
    finally:
        if clima:
            code, _ = pedir(MS0, "/auth/logout", "POST", {}, clima)
            print("Logout CLIMALIMA:", code)
        if frio:
            code, _ = pedir(MS0, "/auth/logout", "POST", {}, frio)
            print("Logout FRIOSUR:", code)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError, ValueError, KeyError) as exc:
        print("Prueba interrumpida:", str(exc)[:160])
        sys.exit(1)
