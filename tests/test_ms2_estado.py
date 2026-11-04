"""Pruebas locales MS2 de activación/desactivación (sin llamadas a AWS)."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from botocore.exceptions import ClientError


TECNICO_ID = "12345678-1234-1234-1234-123456789abc"
OTRO_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def cargar_handler():
    path = Path(__file__).resolve().parents[1] / "backend" / "tecnicos" / "handler.py"
    spec = importlib.util.spec_from_file_location("ms2_tecnicos_test_handler", path)
    modulo = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {
        "TECNICOS_TABLE": "prueba-sin-aws",
        "AGENDA_API_BASE": "https://agenda.example.test/dev",
    }), mock.patch("boto3.resource"):
        spec.loader.exec_module(modulo)
    return modulo


class TestEstadoTecnico(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = cargar_handler()

    def setUp(self):
        self.item = {
            "PK": "TENANT#CLIMALIMA",
            "SK": f"TECNICO#{TECNICO_ID}",
            "tenant_id": "CLIMALIMA",
            "tecnico_id": TECNICO_ID,
            "nombre": "Técnico de prueba",
            "especialidades": ["REPARACION"],
            "activo": True,
            "creado_en": "2026-11-04T00:00:00+00:00",
        }
        self.table = mock.Mock()
        self.table.get_item.side_effect = self.get_item
        self.table.update_item.side_effect = self.update_item
        self.mod.TABLE = self.table
        self.verificar = mock.patch.object(
            self.mod, "comprobar_reservas_en_agenda", return_value=False
        )
        self.check = self.verificar.start()
        self.addCleanup(self.verificar.stop)

    def get_item(self, *, Key, ConsistentRead):
        if (Key["PK"], Key["SK"]) == (self.item["PK"], self.item["SK"]):
            return {"Item": dict(self.item)}
        return {}

    def update_item(self, **kwargs):
        self.assertIn("attribute_exists(PK)", kwargs["ConditionExpression"])
        self.assertEqual(kwargs["ReturnValues"], "ALL_NEW")
        esperado = kwargs["ExpressionAttributeValues"][":anterior"]
        if self.item["activo"] != esperado:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException",
                           "Message": "Condicion"}},
                "UpdateItem",
            )
        self.item["activo"] = kwargs["ExpressionAttributeValues"][":nuevo"]
        self.item["actualizado_en"] = kwargs["ExpressionAttributeValues"][":ahora"]
        return {"Attributes": dict(self.item)}

    def event(self, activo, *, tenant="CLIMALIMA", rol="ADMIN", id=TECNICO_ID,
              token=True, custom_body=None):
        return {
            "requestContext": {
                "authorizer": {"tenant_id": tenant, "usuario_id": "u1", "rol": rol}
            },
            "pathParameters": {"tecnico_id": id},
            "headers": {"Authorization": "Bearer token-de-prueba"} if token else {},
            "body": json.dumps({"activo": activo}) if custom_body is None else
                    json.dumps(custom_body),
        }

    def call(self, event):
        respuesta = self.mod.cambiar_estado(event, None)
        return respuesta["statusCode"], json.loads(respuesta["body"])

    def test_desactivar_y_reactivar(self):
        status, body = self.call(self.event(False))
        self.assertEqual(status, 200)
        self.assertFalse(body["tecnico"]["activo"])
        self.check.assert_called_once_with(TECNICO_ID, "Bearer token-de-prueba")
        self.assertEqual(self.call(self.event(False))[1]["sin_cambios"], True)
        self.assertEqual(self.check.call_count, 1)
        status, body = self.call(self.event(True))
        self.assertEqual(status, 200)
        self.assertTrue(body["tecnico"]["activo"])
        self.assertEqual(self.item["activo"], True)

    def test_sin_rol(self):
        self.assertEqual(self.call(self.event(False, rol="COORDINADOR"))[0], 403)
        self.assertEqual(self.call(self.event(False, rol="TECNICO"))[0], 403)
        self.table.update_item.assert_not_called()

    def test_sin_identidad(self):
        self.assertEqual(self.call(self.event(False, tenant="NO_EXISTE"))[0], 401)

    def test_otra_empresa_y_tecnico_desconocido(self):
        self.assertEqual(self.call(self.event(False, tenant="FRIOSUR"))[0], 404)
        self.assertEqual(self.call(self.event(False, id=OTRO_ID))[0], 404)

    def test_rechaza_forzado_y_no_booleano(self):
        self.assertEqual(self.call(self.event(False, custom_body={
            "activo": False, "tenant_id": "FRIOSUR",
        }))[0], 400)
        for invalid in [0, 1, "false", None, [], {}]:
            self.assertEqual(self.call(self.event(invalid))[0], 400)

    def test_reserva_impide_desactivar(self):
        self.check.return_value = True
        status, body = self.call(self.event(False))
        self.assertEqual(status, 409)
        self.assertIn("visitas reservadas", body["error"])
        self.table.update_item.assert_not_called()

    def test_agenda_fallando_impide_desactivar(self):
        self.check.return_value = None
        self.assertEqual(self.call(self.event(False))[0], 503)
        self.table.update_item.assert_not_called()

    def test_no_permite_mutacion_sin_bearer(self):
        self.assertEqual(self.call(self.event(False, token=False))[0], 401)
        self.table.update_item.assert_not_called()

    def test_cambio_concurrente_devuelve_409(self):
        self.table.update_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException",
                       "Message": "Condicion"}},
            "UpdateItem",
        )
        self.assertEqual(self.call(self.event(False))[0], 409)

    def test_verificacion_agenda_usa_authorization(self):
        self.verificar.stop()
        self.check = None
        respuesta = mock.MagicMock()
        respuesta.status = 200
        with mock.patch.object(self.mod.urllib.request, "urlopen",
                               return_value=respuesta) as fake_http, \
             mock.patch.object(self.mod.json, "load",
                               return_value={"tiene_reservas": True}):
            self.assertTrue(self.mod.comprobar_reservas_en_agenda(
                TECNICO_ID, "Bearer token-de-prueba"
            ))
            solicitud = fake_http.call_args.args[0]
            self.assertTrue(solicitud.full_url.endswith(
                "/tecnicos/" + TECNICO_ID + "/reservas-futuras"
            ))
            self.assertEqual(solicitud.get_header("Authorization"),
                             "Bearer token-de-prueba")


if __name__ == "__main__":
    unittest.main()
