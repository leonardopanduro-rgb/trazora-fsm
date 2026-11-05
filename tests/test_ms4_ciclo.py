"""Pruebas locales MS4: iniciar, reprogramar, cancelar con bloques transaccionales.

No contacta AWS ni modifica las visitas existentes.
"""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from botocore.exceptions import ClientError

VISITA_ID = "11111111-2222-3333-4444-555555555555"
OTRO_ID = "cccccccc-bbbb-aaaa-9999-eeeeeeeeeeee"
ORDEN_ID = "11111111-1111-1111-1111-111111111111"
TECNICO_ID = "22222222-2222-2222-2222-222222222222"
TECNICO_NUEVO = "33333333-3333-3333-3333-333333333333"


def handler():
    path = Path(__file__).resolve().parents[1] / "backend" / "agenda" / "handler.py"
    spec = importlib.util.spec_from_file_location("ms4_ciclo_test_module", path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {
        "AGENDA_TABLE": "tabla-simulada",
        "ORDENES_API_BASE": "https://ordenes.example.test/dev",
        "TECNICOS_API_BASE": "https://tecnicos.example.test/dev",
    }), mock.patch("boto3.resource"), mock.patch("boto3.client"):
        spec.loader.exec_module(module)
    return module


class CicloVisitasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = handler()

    def setUp(self):
        lima = ZoneInfo("America/Lima")
        fecha = datetime.now(lima).date() + timedelta(days=16)
        local = datetime(fecha.year, fecha.month, fecha.day, 10, tzinfo=lima)
        self.inicio = local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
        self.fin = (local + timedelta(hours=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
        self.nuevo_inicio = (local + timedelta(minutes=30)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
        self.nuevo_fin = (local + timedelta(hours=1, minutes=30)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
        self.visit = {
            "PK": "TENANT#CLIMALIMA",
            "SK": "VISITA#" + VISITA_ID,
            "entity_type": "VISITA",
            "tenant_id": "CLIMALIMA",
            "visita_id": VISITA_ID,
            "orden_id": ORDEN_ID,
            "tecnico_id": TECNICO_ID,
            "inicio": self.inicio,
            "fin": self.fin,
            "estado": "PROGRAMADA",
            "creada_en": "2026-11-04T16:00:00+00:00",
            "version": 1,
        }
        self.table = mock.Mock()
        self.table.get_item.side_effect = self.read
        self.table.update_item.return_value = {
            "Attributes": {**self.visit, "estado": "EN_ATENCION", "version": 2}
        }
        self.mod.TABLE = self.table
        self.client = mock.Mock()
        self.mod.DB_CLIENT = self.client
        patch = mock.patch.object(self.mod, "get_protegido", side_effect=self.remote)
        self.remote_mock = patch.start()
        self.addCleanup(patch.stop)

    def read(self, *, Key, ConsistentRead):
        if Key["PK"] == "TENANT#CLIMALIMA" and Key["SK"] == self.visit["SK"]:
            return {"Item": dict(self.visit)}
        return {}

    def remote(self, url, path, token):
        if path == "/ordenes/" + ORDEN_ID:
            return {"orden": {
                "orden_id": ORDEN_ID,
                "tenant_id": "CLIMALIMA",
                "tipo_servicio": "MANTENIMIENTO",
                "estado": "ABIERTA",
            }}, 200
        if path.startswith("/tecnicos/") and "/jornadas?" not in path:
            id = path.split("/")[-1]
            return {"tecnico": {
                "tecnico_id": id,
                "tenant_id": "CLIMALIMA",
                "activo": True,
                "especialidades": ["MANTENIMIENTO"],
            }}, 200
        if "/jornadas?" in path:
            tecnico_id = path.split("/")[2]
            fecha = self.inicio[:10]  # Lima examples were chosen at 10:00, adjust date below.
            fecha = datetime.fromisoformat(self.inicio.replace("Z", "+00:00")).astimezone(
                ZoneInfo("America/Lima")
            ).date().isoformat()
            return {"jornadas": [{
                "tecnico_id": tecnico_id,
                "tenant_id": "CLIMALIMA",
                "fecha": fecha,
                "intervalos": [{"inicio": "09:00", "fin": "13:00"}],
            }]}, 200
        raise AssertionError("API no esperada: " + path)

    def event(self, ruta, body=None, *, tenant="CLIMALIMA", rol="ADMIN",
              visita_id=VISITA_ID, auth=True):
        return {
            "requestContext": {
                "authorizer": {"tenant_id": tenant, "usuario_id": "u1", "rol": rol}
            },
            "pathParameters": {"visita_id": visita_id},
            "headers": {"Authorization": "Bearer prueba-no-real"} if auth else {},
            "body": json.dumps(body if body is not None else {}),
            "httpMethod": ruta,
        }

    def call(self, fn, event):
        result = fn(event, None)
        return result["statusCode"], json.loads(result["body"])

    def reprogramar_body(self, tech=TECNICO_ID):
        return {"tecnico_id": tech, "inicio": self.nuevo_inicio, "fin": self.nuevo_fin}

    def test_iniciar_visita(self):
        code, body = self.call(self.mod.iniciar, self.event("POST"))
        self.assertEqual(code, 200)
        self.assertEqual(body["visita"]["estado"], "EN_ATENCION")
        self.assertEqual(body["visita"]["version"], 2)
        self.table.update_item.assert_called_once()
        kwargs = self.table.update_item.call_args.kwargs
        self.assertIn("#estado = :programada", kwargs["ConditionExpression"])
        self.assertEqual(kwargs["ExpressionAttributeValues"][":nueva_version"], 2)

    def test_iniciar_ya_iniciada_idempotente(self):
        self.visit["estado"] = "EN_ATENCION"
        code, body = self.call(self.mod.iniciar, self.event("POST"))
        self.assertEqual(code, 200)
        self.assertTrue(body["sin_cambios"])
        self.table.update_item.assert_not_called()

    def test_iniciar_cancelada_rechazada(self):
        self.visit["estado"] = "CANCELADA"
        code, _ = self.call(self.mod.iniciar, self.event("POST"))
        self.assertEqual(code, 409)

    def test_iniciar_legacy_sin_version(self):
        self.visit.pop("version")
        code, _ = self.call(self.mod.iniciar, self.event("POST"))
        self.assertEqual(code, 200)
        expr = self.table.update_item.call_args.kwargs["ConditionExpression"]
        self.assertIn("attribute_not_exists(#version)", expr)

    def test_iniciar_concurrencia(self):
        self.table.update_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "condicion"}},
            "UpdateItem",
        )
        code, _ = self.call(self.mod.iniciar, self.event("POST"))
        self.assertEqual(code, 409)

    def test_reprogramar_mueve_solo_bloques_diferentes(self):
        code, body = self.call(
            self.mod.reprogramar, self.event("PATCH", self.reprogramar_body())
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["visita"]["inicio"], self.nuevo_inicio)
        self.assertEqual(body["visita"]["version"], 2)
        actions = self.client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(actions), 4)  # visita, bloque viejo, bloque nuevo, control
        self.assertEqual(sum("Put" in a for a in actions), 1)
        self.assertEqual(sum("Delete" in a for a in actions), 1)
        self.assertEqual(sum("Update" in a for a in actions), 1)
        self.assertEqual(sum("ConditionCheck" in a for a in actions), 1)
        unique_keys = []
        for action in actions:
            kind, body = next(iter(action.items()))
            item = body.get("Item", body.get("Key"))
            unique_keys.append((item["PK"]["S"], item["SK"]["S"]))
        self.assertEqual(len(unique_keys), len(set(unique_keys)))

    def test_reprogramar_cambio_tecnico(self):
        code, body = self.call(
            self.mod.reprogramar,
            self.event("PATCH", self.reprogramar_body(TECNICO_NUEVO)),
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["visita"]["tecnico_id"], TECNICO_NUEVO)
        actions = self.client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(sum("Delete" in a for a in actions), 2)
        self.assertEqual(sum("Put" in a for a in actions), 2)

    def test_reprogramar_mismo_horario_idempotente(self):
        data = {"tecnico_id": TECNICO_ID, "inicio": self.inicio, "fin": self.fin}
        code, body = self.call(self.mod.reprogramar, self.event("PATCH", data))
        self.assertEqual(code, 200)
        self.assertTrue(body["sin_cambios"])
        self.client.transact_write_items.assert_not_called()

    def test_reprogramar_otra_empresa(self):
        code, _ = self.call(
            self.mod.reprogramar,
            self.event("PATCH", self.reprogramar_body(), tenant="FRIOSUR"),
        )
        self.assertEqual(code, 404)

    def test_reprogramar_validacion_400(self):
        data = self.reprogramar_body()
        data["tenant_id"] = "FRIOSUR"
        code, _ = self.call(self.mod.reprogramar, self.event("PATCH", data))
        self.assertEqual(code, 400)

    def test_reprogramar_condicion_fallida_409(self):
        self.client.transact_write_items.side_effect = ClientError(
            {"Error": {"Code": "TransactionCanceledException", "Message": "conflicto"}},
            "TransactWriteItems",
        )
        code, _ = self.call(
            self.mod.reprogramar, self.event("PATCH", self.reprogramar_body())
        )
        self.assertEqual(code, 409)

    def test_cancelar_liberar_bloques_y_decrementar(self):
        code, body = self.call(self.mod.cancelar, self.event("POST"))
        self.assertEqual(code, 200)
        self.assertEqual(body["visita"]["estado"], "CANCELADA")
        actions = self.client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(actions), 4)
        self.assertEqual(sum("Delete" in a for a in actions), 2)
        control = actions[-1]["Update"]
        self.assertIn("ADD visitas_activas :menos", control["UpdateExpression"])
        self.assertEqual(control["ExpressionAttributeValues"][":menos"]["N"], "-1")

    def test_cancelar_repetida_sin_efectos(self):
        self.visit["estado"] = "CANCELADA"
        code, body = self.call(self.mod.cancelar, self.event("POST"))
        self.assertEqual(code, 200)
        self.assertTrue(body["sin_cambios"])
        self.client.transact_write_items.assert_not_called()

    def test_cancelar_iniciada_rechazada(self):
        self.visit["estado"] = "EN_ATENCION"
        code, _ = self.call(self.mod.cancelar, self.event("POST"))
        self.assertEqual(code, 409)
        self.client.transact_write_items.assert_not_called()

    def test_cancelar_concurrencia(self):
        self.client.transact_write_items.side_effect = ClientError(
            {"Error": {"Code": "TransactionCanceledException", "Message": "conflicto"}},
            "TransactWriteItems",
        )
        code, _ = self.call(self.mod.cancelar, self.event("POST"))
        self.assertEqual(code, 409)

    def test_denegado_rol(self):
        for action, body in [
            (self.mod.iniciar, {}),
            (self.mod.reprogramar, self.reprogramar_body()),
            (self.mod.cancelar, {}),
        ]:
            self.assertEqual(self.call(action, self.event("POST", body, rol="TECNICO"))[0], 403)

    def test_denegado_sin_identidad(self):
        code, _ = self.call(self.mod.iniciar, self.event("POST", tenant="OTRO"))
        self.assertEqual(code, 401)

    def test_invalid_id(self):
        code, _ = self.call(self.mod.cancelar, self.event("POST", visita_id="invalido"))
        self.assertEqual(code, 400)

    def test_order_status_no_valid(self):
        def fake_remote(base, path, auth):
            if "/ordenes/" in path:
                return {"orden": {
                    "tenant_id": "CLIMALIMA", "orden_id": ORDEN_ID,
                    "estado": "CERRADA", "tipo_servicio": "MANTENIMIENTO"
                }}, 200
            return self.remote(base, path, auth)
        self.remote_mock.side_effect = fake_remote
        code, _ = self.call(
            self.mod.reprogramar, self.event("PATCH", self.reprogramar_body())
        )
        self.assertEqual(code, 409)

    def test_tech_inactive(self):
        def fake_remote(base, path, auth):
            if path == "/tecnicos/" + TECNICO_ID:
                return {"tecnico": {
                    "tenant_id": "CLIMALIMA", "tecnico_id": TECNICO_ID,
                    "activo": False, "especialidades": ["MANTENIMIENTO"]
                }}, 200
            return self.remote(base, path, auth)
        self.remote_mock.side_effect = fake_remote
        code, _ = self.call(
            self.mod.reprogramar, self.event("PATCH", self.reprogramar_body())
        )
        self.assertEqual(code, 409)


if __name__ == "__main__":
    unittest.main()
