"""Pruebas sin AWS de la Lambda manual SQS consumidora de Órdenes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "manual_lambdas" / "ordenes_consumidor" / "lambda_function.py"
ARN = "arn:aws:sqs:us-east-1:975050277936:trazora-eventos-ordenes-dev"
ORDER_ID = "11111111-2222-3333-4444-555555555555"
PART_ID = "22222222-3333-4444-5555-666666666666"
VISIT_ID = "33333333-4444-5555-6666-777777777777"
EVENT_ID = "44444444-5555-6666-7777-888888888888"


def cargar():
    spec = importlib.util.spec_from_file_location("ordenes_manual_test", SOURCE)
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {
        "ORDENES_TABLE": "trazora-ordenes-dev", "SQS_ORDENES_ARN": ARN
    }), mock.patch("boto3.resource"), mock.patch("boto3.client"):
        spec.loader.exec_module(mod)
    return mod


class OrdenesConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = cargar()

    def setUp(self):
        self.table = mock.Mock()
        self.ddb = mock.Mock()
        self.mod.DB = self.table
        self.mod.CLIENT = self.ddb
        self.orden = {
            "PK": "TENANT#CLIMALIMA",
            "SK": "ORDEN#" + ORDER_ID,
            "orden_id": ORDER_ID,
            "tenant_id": "CLIMALIMA",
            "estado": "ABIERTA",
            "tipo_servicio": "REPARACION",
        }
        self.table.get_item.side_effect = self.leer

    def leer(self, *, Key, ConsistentRead):
        if Key["SK"].startswith("INBOX#"):
            return {}
        if Key["PK"] == "TENANT#CLIMALIMA" and Key["SK"] == self.orden["SK"]:
            return {"Item": dict(self.orden)}
        return {}

    def evento(self):
        return {
            "event_id": EVENT_ID,
            "event_type": "ParteFinalizado",
            "schema_version": 1,
            "tenant_id": "CLIMALIMA",
            "aggregate_type": "PARTE",
            "aggregate_id": PART_ID,
            "aggregate_version": 3,
            "occurred_at": "2026-11-04T23:00:00+00:00",
            "correlation_id": VISIT_ID,
            "data": {
                "visita_id": VISIT_ID,
                "orden_id": ORDER_ID,
                "parte_id": PART_ID,
                "resultado": "RESUELTO",
            },
        }

    def test_evento_vacio_no_escribe(self):
        self.assertEqual(
            self.mod.lambda_handler({"Records": []}, None),
            {"procesados": 0, "duplicados": 0},
        )
        self.table.get_item.assert_not_called()

    def test_resuelto_guarda_historial_inbox_y_pendiente_de_cierre(self):
        self.assertEqual(self.mod.procesar(self.evento()), "actualizado")
        actions = self.ddb.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(actions), 3)
        self.assertEqual([list(a)[0] for a in actions], ["Update", "Put", "Put"])
        update = actions[0]["Update"]
        vals = update["ExpressionAttributeValues"]
        self.assertEqual(update["Key"]["SK"]["S"], "ORDEN#" + ORDER_ID)
        self.assertEqual(vals[":nuevo"], {"S": "PENDIENTE_DE_CIERRE"})
        self.assertEqual(vals[":resultado"], {"S": "RESUELTO"})
        self.assertEqual(vals[":revisita"], {"BOOL": False})
        self.assertIn("tenant_id = :tenant", update["ConditionExpression"])
        historial = actions[1]["Put"]["Item"]
        self.assertEqual(historial["entity_type"], {"S": "HISTORIAL_ORDEN"})
        self.assertEqual(historial["event_id"], {"S": EVENT_ID})
        inbox = actions[2]["Put"]["Item"]
        self.assertEqual(inbox["entity_type"], {"S": "INBOX"})
        self.assertEqual(inbox["SK"], {"S": "INBOX#" + EVENT_ID})

    def test_requiere_revisita_mantiene_abierta(self):
        e = self.evento()
        e["data"]["resultado"] = "REQUIERE_REVISITA"
        self.assertEqual(self.mod.procesar(e), "actualizado")
        vals = self.ddb.transact_write_items.call_args.kwargs["TransactItems"][0][
            "Update"]["ExpressionAttributeValues"]
        self.assertEqual(vals[":nuevo"], {"S": "ABIERTA"})
        self.assertEqual(vals[":revisita"], {"BOOL": True})

    def test_no_atendido_mantiene_abierta(self):
        e = self.evento()
        e["data"]["resultado"] = "NO_ATENDIDO"
        self.assertEqual(self.mod.procesar(e), "actualizado")
        vals = self.ddb.transact_write_items.call_args.kwargs["TransactItems"][0][
            "Update"]["ExpressionAttributeValues"]
        self.assertEqual(vals[":revisita"], {"BOOL": True})

    def test_event_id_duplicado_idempotente(self):
        e = self.evento()
        digest = hashlib.sha256(json.dumps(
            e, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        self.table.get_item.side_effect = lambda **kw: (
            {"Item": {"payload_sha256": digest}} if
            kw["Key"]["SK"].startswith("INBOX#") else {"Item": self.orden}
        )
        self.assertEqual(self.mod.procesar(e), "duplicado")
        self.ddb.transact_write_items.assert_not_called()

    def test_evento_id_reusado_invalido(self):
        self.table.get_item.side_effect = lambda **kw: (
            {"Item": {"payload_sha256": "otro_hash"}} if
            kw["Key"]["SK"].startswith("INBOX#") else {"Item": self.orden}
        )
        with self.assertRaisesRegex(ValueError, "reutilizado"):
            self.mod.procesar(self.evento())

    def test_otra_empresa_rechazada(self):
        e = self.evento()
        e["tenant_id"] = "FRIOSUR"
        with self.assertRaisesRegex(ValueError, "Orden inexistente"):
            self.mod.procesar(e)
        self.ddb.transact_write_items.assert_not_called()

    def test_orden_cerrada_no_se_reabre(self):
        self.orden["estado"] = "CERRADA"
        with self.assertRaisesRegex(ValueError, "Orden cerrada"):
            self.mod.procesar(self.evento())
        self.ddb.transact_write_items.assert_not_called()

    def test_evento_stale_rechazado(self):
        self.orden["ultimo_evento_ocurrido_en"] = "2030-01-01T00:00:00.000000+00:00"
        with self.assertRaisesRegex(ValueError, "Evento antiguo"):
            self.mod.procesar(self.evento())
        self.ddb.transact_write_items.assert_not_called()

    def test_tipo_y_contrato_invalido(self):
        e = self.evento()
        e["event_type"] = "VisitaIniciada"
        with self.assertRaisesRegex(ValueError, "Contrato"):
            self.mod.procesar(e)
        e = self.evento()
        e["schema_version"] = "1"
        with self.assertRaisesRegex(ValueError, "Contrato"):
            self.mod.procesar(e)

    def test_origen_sqs_invalido_rechazado(self):
        record = {
            "eventSource": "aws:sqs",
            "eventSourceARN": ARN + "-otra",
            "messageId": "demo",
            "body": json.dumps(self.evento()),
        }
        with self.assertRaisesRegex(ValueError, "Origen SQS"):
            self.mod.lambda_handler({"Records": [record]}, None)
        self.ddb.transact_write_items.assert_not_called()

    def test_mensaje_sqs_valido(self):
        record = {
            "eventSource": "aws:sqs", "eventSourceARN": ARN,
            "messageId": "demo", "body": json.dumps(self.evento()),
        }
        self.assertEqual(
            self.mod.lambda_handler({"Records": [record]}, None),
            {"procesados": 1, "duplicados": 0},
        )

    def test_error_transaccion_reintento(self):
        self.ddb.transact_write_items.side_effect = ClientError(
            {"Error": {"Code": "TransactionCanceledException", "Message": "fail"}},
            "TransactWriteItems",
        )
        with self.assertRaises(ClientError):
            self.mod.procesar(self.evento())


if __name__ == "__main__":
    unittest.main()
