"""Pruebas locales de GET /ordenes/{id}/historial, sin AWS."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

ORDEN = "11111111-2222-3333-4444-555555555555"


def importar():
    ruta = Path(__file__).resolve().parents[1] / "backend" / "ordenes" / "handler.py"
    spec = importlib.util.spec_from_file_location("ms3_historial_eda", ruta)
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {
        "ORDENES_TABLE": "tabla-test", "CLIENTES_API_BASE": "https://example.test/dev"
    }, clear=True), mock.patch("boto3.resource"):
        spec.loader.exec_module(mod)
    return mod


class HistorialTest(unittest.TestCase):
    def setUp(self):
        self.mod = importar()
        self.tabla = mock.Mock()
        self.mod.TABLE = self.tabla
        self.tabla.get_item.return_value = {"Item": {
            "tenant_id": "CLIMALIMA", "orden_id": ORDEN, "estado": "ABIERTA",
        }}
        self.tabla.query.return_value = {"Items": [{
            "event_id": "55555555-6666-7777-8888-999999999999",
            "event_type": "ParteFinalizado", "resultado": "RESUELTO",
        }]}

    def pedir(self, tenant="CLIMALIMA", rol="ADMIN", params=None):
        return {
            "pathParameters": {"orden_id": ORDEN},
            "queryStringParameters": params or {},
            "requestContext": {"authorizer": {
                "tenant_id": tenant, "rol": rol, "usuario_id": "usuario-test"
            }},
        }

    def test_historial_tenant_autorizado(self):
        resp = self.mod.historial(self.pedir(), None)
        self.assertEqual(resp["statusCode"], 200)
        cuerpo = json.loads(resp["body"])
        self.assertEqual(cuerpo["historial"][0]["event_type"], "ParteFinalizado")
        self.assertIsNone(cuerpo["next_cursor"])
        self.assertEqual(self.tabla.query.call_count, 1)

    def test_orden_ajena_404(self):
        self.tabla.get_item.return_value = {"Item": {
            "tenant_id": "FRIOSUR", "orden_id": ORDEN
        }}
        resp = self.mod.historial(self.pedir(), None)
        self.assertEqual(resp["statusCode"], 404)
        self.tabla.query.assert_not_called()

    def test_tecnico_no_tiene_permiso(self):
        resp = self.mod.historial(self.pedir(rol="TECNICO"), None)
        self.assertEqual(resp["statusCode"], 403)
        self.tabla.get_item.assert_not_called()

    def test_limite_invalido(self):
        resp = self.mod.historial(self.pedir(params={"limit": "500"}), None)
        self.assertEqual(resp["statusCode"], 400)
        self.tabla.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
