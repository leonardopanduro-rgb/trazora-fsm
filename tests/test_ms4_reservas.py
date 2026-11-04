"""Pruebas sin AWS del endpoint protegido de reservas futuras de MS4."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock


TEC_ID = "12345678-1234-1234-1234-123456789abc"


def cargar_handler():
    path = Path(__file__).resolve().parents[1] / "backend" / "agenda" / "handler.py"
    spec = importlib.util.spec_from_file_location("ms4_agenda_reservas_test_handler", path)
    modulo = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {
        "AGENDA_TABLE": "prueba-agenda-sin-aws",
        "ORDENES_API_BASE": "https://ordenes.example.test/dev",
        "TECNICOS_API_BASE": "https://tecnicos.example.test/dev",
    }), mock.patch("boto3.resource"), mock.patch("boto3.client"):
        spec.loader.exec_module(modulo)
    return modulo


class TestReservasFuturas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = cargar_handler()

    def setUp(self):
        self.table = mock.Mock()
        self.mod.TABLE = self.table
        self.table.query.return_value = {"Items": []}

    def event(self, *, tenant="CLIMALIMA", rol="ADMIN", tecnico_id=TEC_ID):
        return {
            "requestContext": {
                "authorizer": {"tenant_id": tenant, "usuario_id": "u1", "rol": rol}
            },
            "pathParameters": {"tecnico_id": tecnico_id},
        }

    def call(self, event):
        respuesta = self.mod.reservas_futuras(event, None)
        return respuesta["statusCode"], json.loads(respuesta["body"])

    def test_sin_reserva(self):
        status, body = self.call(self.event())
        self.assertEqual(status, 200)
        self.assertIs(body["tiene_reservas"], False)
        self.assertEqual(body["tecnico_id"], TEC_ID)
        options = self.table.query.call_args.kwargs
        self.assertIs(options["ConsistentRead"], True)
        self.assertEqual(options["Limit"], 1)

    def test_con_bloque_reservado(self):
        self.table.query.return_value = {"Items": [{"visita_id": "demo"}]}
        status, body = self.call(self.event())
        self.assertEqual(status, 200)
        self.assertIs(body["tiene_reservas"], True)

    def test_denegado_otros_roles(self):
        self.assertEqual(self.call(self.event(rol="TECNICO"))[0], 403)
        self.table.query.assert_not_called()

    def test_denegado_sin_identidad(self):
        self.assertEqual(self.call(self.event(tenant="INEXISTENTE"))[0], 401)
        self.table.query.assert_not_called()

    def test_parametro_malformado(self):
        self.assertEqual(self.call(self.event(tecnico_id="falso"))[0], 400)
        self.table.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
