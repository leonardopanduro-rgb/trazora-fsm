"""MS5: pruebas locales de finalización y OUTBOX, sin AWS real."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
from decimal import Decimal

from botocore.exceptions import ClientError

PARTE_ID = "11111111-2222-3333-4444-555555555555"
VISITA_ID = "22222222-3333-4444-5555-666666666666"
ORDEN_ID = "33333333-4444-5555-6666-777777777777"
EVIDENCIA_ID = "44444444-5555-6666-7777-888888888888"


def importar_handler():
    root = Path(__file__).resolve().parents[1]
    directory = root / "backend" / "partes"
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location(
        "ms5_partes_finalizar_test_handler", directory / "handler.py"
    )
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {
        "PARTES_TABLE": "tabla-prueba",
        "EVIDENCIAS_BUCKET": "bucket-prueba",
        "AGENDA_API_BASE": "https://agenda.example.test/dev",
        "AWS_REGION": "us-east-1",
    }), mock.patch("boto3.resource"), mock.patch("boto3.client"):
        spec.loader.exec_module(module)
    return module


class FinalizarParteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = importar_handler()

    def setUp(self):
        self.part = {
            "PK": "TENANT#CLIMALIMA",
            "SK": "PARTE#" + PARTE_ID,
            "tenant_id": "CLIMALIMA",
            "parte_id": PARTE_ID,
            "visita_id": VISITA_ID,
            "orden_id": ORDEN_ID,
            "estado": "BORRADOR",
            "diagnostico": "Filtro obstruido",
            "tareas": ["Limpieza de filtro", "Prueba de enfriamiento"],
            "resultado": "RESUELTO",
            "version": Decimal(2),
            "creado_en": "2026-11-04T13:00:00Z",
            "actualizado_en": "2026-11-04T13:30:00Z",
        }
        self.table = mock.Mock()
        self.table.get_item.side_effect = self.get_item
        self.table.query.return_value = {"Items": [{
            "estado": "CONFIRMADA",
            "tenant_id": "CLIMALIMA",
            "parte_id": PARTE_ID,
            "evidencia_id": EVIDENCIA_ID,
        }]}
        self.mod.TABLE = self.table
        self.db = mock.Mock()
        self.mod.DYNAMODB = self.db
        visit_patch = mock.patch.object(self.mod, "get_visit", return_value=({
            "tenant_id": "CLIMALIMA",
            "visita_id": VISITA_ID,
            "orden_id": ORDEN_ID,
            "estado": "EN_ATENCION",
        }, 200))
        self.get_visit = visit_patch.start()
        self.addCleanup(visit_patch.stop)

    def get_item(self, *, Key, ConsistentRead):
        if Key == {"PK": "TENANT#CLIMALIMA", "SK": "PARTE#" + PARTE_ID}:
            return {"Item": dict(self.part)}
        return {}

    def event(self, body=None, *, tenant="CLIMALIMA", rol="ADMIN",
              parte_id=PARTE_ID, authorized=True):
        return {
            "pathParameters": {"parte_id": parte_id},
            "requestContext": {
                "authorizer": {
                    "tenant_id": tenant,
                    "usuario_id": "admin-test",
                    "rol": rol,
                },
            },
            "headers": {"Authorization": "Bearer prueba"} if authorized else {},
            "body": json.dumps({"version": 2} if body is None else body),
        }

    def call(self, event):
        result = self.mod.finalizar(event, None)
        return result["statusCode"], json.loads(result["body"])

    def test_finalizar_guarda_parte_y_outbox_en_una_transaccion(self):
        code, payload = self.call(self.event())
        self.assertEqual(code, 200)
        self.assertEqual(payload["parte"]["estado"], "FINALIZADO")
        self.assertEqual(payload["parte"]["version"], 3)
        self.assertFalse(payload["sin_cambios"])
        self.assertEqual(payload["evento"]["event_type"], "ParteFinalizado")
        self.assertEqual(payload["evento"]["estado"], "PENDIENTE_PUBLICACION")

        acciones = self.db.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(acciones), 2)
        self.assertIn("Update", acciones[0])
        self.assertIn("Put", acciones[1])
        update = acciones[0]["Update"]
        outbox = acciones[1]["Put"]
        self.assertIn("#estado = :borrador", update["ConditionExpression"])
        self.assertEqual(update["ExpressionAttributeValues"][":version"], {"N": "2"})
        self.assertEqual(update["ExpressionAttributeValues"][":nueva_version"], {"N": "3"})
        self.assertEqual(outbox["Item"]["entity_type"]["S"], "OUTBOX")
        self.assertEqual(outbox["Item"]["estado"]["S"], "PENDIENTE")
        event = outbox["Item"]["payload"]["M"]
        self.assertEqual(event["event_type"]["S"], "ParteFinalizado")
        self.assertEqual(event["tenant_id"]["S"], "CLIMALIMA")
        self.assertEqual(event["data"]["M"]["orden_id"]["S"], ORDEN_ID)
        self.assertEqual(event["data"]["M"]["visita_id"]["S"], VISITA_ID)

    def test_reintento_no_crea_evento_nuevo(self):
        self.part.update({
            "estado": "FINALIZADO",
            "version": Decimal(3),
            "evento_finalizacion_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        })
        code, result = self.call(self.event())
        self.assertEqual(code, 200)
        self.assertTrue(result["sin_cambios"])
        self.assertEqual(
            result["evento"]["event_id"], "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        self.db.transact_write_items.assert_not_called()
        self.get_visit.assert_not_called()

    def test_tenant_ajeno_devuelve_404(self):
        code, _ = self.call(self.event(tenant="FRIOSUR"))
        self.assertEqual(code, 404)
        self.db.transact_write_items.assert_not_called()

    def test_sin_rol(self):
        self.assertEqual(self.call(self.event(rol="TECNICO"))[0], 403)

    def test_tenant_no_reconocido(self):
        self.assertEqual(self.call(self.event(tenant="DUDOSO"))[0], 401)

    def test_rechaza_input_invalido(self):
        for bad in [True, False, 0, "2", None, {}, []]:
            self.assertEqual(self.call(self.event(body={"version": bad}))[0], 400)
        self.assertEqual(self.call(self.event(body={
            "version": 2, "tenant_id": "FRIOSUR"
        }))[0], 400)

    def test_version_anticuada(self):
        self.assertEqual(self.call(self.event(body={"version": 1}))[0], 409)

    def test_estado_incompatible(self):
        self.part["estado"] = "CANCELADO"
        self.assertEqual(self.call(self.event())[0], 409)

    def test_diagnostico_obligatorio(self):
        self.part["diagnostico"] = ""
        self.assertEqual(self.call(self.event())[0], 422)

    def test_tareas_obligatorias(self):
        self.part["tareas"] = []
        self.assertEqual(self.call(self.event())[0], 422)

    def test_resultado_obligatorio(self):
        self.part["resultado"] = "PENDIENTE"
        self.assertEqual(self.call(self.event())[0], 422)

    def test_visita_debe_estar_en_atencion(self):
        self.get_visit.return_value = ({
            "tenant_id": "CLIMALIMA", "visita_id": VISITA_ID,
            "orden_id": ORDEN_ID, "estado": "PROGRAMADA",
        }, 200)
        self.assertEqual(self.call(self.event())[0], 409)

    def test_orden_debe_coincidir(self):
        self.get_visit.return_value = ({
            "tenant_id": "CLIMALIMA", "visita_id": VISITA_ID,
            "orden_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "estado": "EN_ATENCION",
        }, 200)
        self.assertEqual(self.call(self.event())[0], 404)

    def test_visita_no_disponible(self):
        self.get_visit.return_value = (None, 502)
        self.assertEqual(self.call(self.event())[0], 502)

    def test_al_menos_una_evidencia_confirmada(self):
        self.table.query.return_value = {"Items": [
            {"estado": "PENDIENTE", "tenant_id": "CLIMALIMA", "parte_id": PARTE_ID}
        ]}
        self.assertEqual(self.call(self.event())[0], 422)

    def test_evidencia_confirmada_paginada(self):
        self.table.query.side_effect = [
            {"Items": [{"estado": "PENDIENTE"}],
             "LastEvaluatedKey": {"PK": "TENANT#CLIMALIMA", "SK": "SK_NEXT"}},
            {"Items": [{"estado": "CONFIRMADA", "tenant_id": "CLIMALIMA",
                        "parte_id": PARTE_ID}]},
        ]
        self.assertEqual(self.call(self.event())[0], 200)
        self.assertEqual(self.table.query.call_count, 2)

    def test_transaccion_duplicada_se_rechaza(self):
        self.db.transact_write_items.side_effect = ClientError(
            {"Error": {"Code": "TransactionCanceledException",
                       "Message": "Condicion"}},
            "TransactWriteItems",
        )
        self.assertEqual(self.call(self.event())[0], 409)

    def test_ausencia_token_no_modifica(self):
        self.assertEqual(self.call(self.event(authorized=False))[0], 401)
        self.db.transact_write_items.assert_not_called()


if __name__ == "__main__":
    unittest.main()
