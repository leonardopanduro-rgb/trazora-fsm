"""Pruebas sin AWS de la Lambda manual consumidora SQS de Agenda."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "manual_lambdas" / "agenda_consumidor" / "lambda_function.py"
ARN = "arn:aws:sqs:us-east-1:975050277936:trazora-eventos-agenda-dev"
VISITA = "11111111-2222-3333-4444-555555555555"
PARTE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ORDEN = "22222222-3333-4444-5555-666666666666"
EVENTO = "33333333-4444-5555-6666-777777777777"
TECNICO = "44444444-5555-6666-7777-888888888888"


def load_handler():
    spec = importlib.util.spec_from_file_location("consumidor_agenda_manual", HANDLER)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {
        "AGENDA_TABLE": "trazora-agenda-dev", "SQS_AGENDA_ARN": ARN
    }), mock.patch("boto3.resource"), mock.patch("boto3.client"):
        spec.loader.exec_module(module)
    return module


class TestSQSAgendaManual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_handler()

    def setUp(self):
        self.table = mock.Mock()
        self.client = mock.Mock()
        self.mod.DB = self.table
        self.mod.CLIENT = self.client
        self.item = {
            "PK": "TENANT#CLIMALIMA",
            "SK": "VISITA#" + VISITA,
            "entity_type": "VISITA",
            "tenant_id": "CLIMALIMA",
            "visita_id": VISITA,
            "orden_id": ORDEN,
            "tecnico_id": TECNICO,
            "inicio": "2030-11-05T15:00:00Z",
            "fin": "2030-11-05T16:00:00Z",
            "estado": "EN_ATENCION",
            "version": 2,
        }
        self.table.get_item.side_effect = self.read

    def read(self, *, Key, ConsistentRead):
        if Key["SK"].startswith("INBOX#"):
            return {}
        if Key["SK"] == self.item["SK"] and Key["PK"] == self.item["PK"]:
            return {"Item": dict(self.item)}
        return {}

    def evento(self):
        return {
            "event_id": EVENTO,
            "event_type": "ParteFinalizado",
            "schema_version": 1,
            "tenant_id": "CLIMALIMA",
            "aggregate_type": "PARTE",
            "aggregate_id": PARTE,
            "aggregate_version": 3,
            "occurred_at": "2030-11-05T16:00:00+00:00",
            "correlation_id": VISITA,
            "data": {
                "visita_id": VISITA,
                "orden_id": ORDEN,
                "parte_id": PARTE,
                "resultado": "RESUELTO",
            },
        }

    def test_vacio_no_hace_lecturas(self):
        self.assertEqual(
            self.mod.lambda_handler({"Records": []}, None),
            {"procesados": 0, "duplicados": 0},
        )
        self.table.get_item.assert_not_called()

    def test_transaccion_finaliza_y_libera_reservas(self):
        self.assertEqual(self.mod.procesar(self.evento()), "finalizado")
        actions = self.client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(actions), 5)
        self.assertEqual(sum("Delete" in a for a in actions), 2)
        self.assertEqual(sum("Update" in a for a in actions), 2)
        self.assertEqual(sum("Put" in a for a in actions), 1)
        first = actions[0]["Update"]
        self.assertEqual(first["Key"]["SK"]["S"], "VISITA#" + VISITA)
        self.assertIn("#estado = :en_atencion", first["ConditionExpression"])
        self.assertEqual(first["ExpressionAttributeValues"][":finalizada"], {"S": "FINALIZADA"})
        control = actions[-2]["Update"]
        self.assertEqual(control["ExpressionAttributeValues"][":menos"], {"N": "-1"})
        inbox = actions[-1]["Put"]["Item"]
        self.assertEqual(inbox["SK"]["S"], "INBOX#" + EVENTO)
        self.assertEqual(inbox["entity_type"]["S"], "INBOX")
        self.assertEqual(inbox["tenant_id"]["S"], "CLIMALIMA")

    def test_duplicado_ignora_segundo_evento(self):
        e = self.evento()
        digest = hashlib.sha256(json.dumps(
            e, sort_keys=True, ensure_ascii=False
        ).encode()).hexdigest()
        self.table.get_item.side_effect = lambda **kw: (
            {"Item": {"payload_sha256": digest}} if
            kw["Key"]["SK"].startswith("INBOX#") else {"Item": self.item}
        )
        self.assertEqual(self.mod.procesar(e), "duplicado")
        self.client.transact_write_items.assert_not_called()

    def test_event_id_reutilizado_rechazado(self):
        self.table.get_item.side_effect = lambda **kw: (
            {"Item": {"payload_sha256": "otro"}} if
            kw["Key"]["SK"].startswith("INBOX#") else {"Item": self.item}
        )
        with self.assertRaisesRegex(ValueError, "Event ID"):
            self.mod.procesar(self.evento())

    def test_otra_empresa_no_actualiza_climalima(self):
        e = self.evento()
        e["tenant_id"] = "FRIOSUR"
        with self.assertRaisesRegex(ValueError, "Visita"):
            self.mod.procesar(e)
        self.client.transact_write_items.assert_not_called()

    def test_estado_no_valido_rechazado(self):
        self.item["estado"] = "CANCELADA"
        with self.assertRaisesRegex(ValueError, "no finalizable"):
            self.mod.procesar(self.evento())
        self.client.transact_write_items.assert_not_called()

    def test_tipo_evento_invalido(self):
        e = self.evento()
        e["event_type"] = "OrdenCancelada"
        with self.assertRaisesRegex(ValueError, "no admitido"):
            self.mod.procesar(e)

    def test_origen_sqs_invalido(self):
        record = {
            "eventSource": "aws:sqs",
            "eventSourceARN": ARN + "-desconocida",
            "messageId": "test1",
            "body": json.dumps(self.evento()),
        }
        with self.assertRaisesRegex(ValueError, "Origen SQS"):
            self.mod.lambda_handler({"Records": [record]}, None)
        self.client.transact_write_items.assert_not_called()

    def test_sqs_valida_entrega(self):
        record = {
            "eventSource": "aws:sqs", "eventSourceARN": ARN,
            "messageId": "test2", "body": json.dumps(self.evento()),
        }
        self.assertEqual(
            self.mod.lambda_handler({"Records": [record]}, None),
            {"procesados": 1, "duplicados": 0},
        )

    def test_transaccion_falla_sin_inbox_y_reintenta(self):
        self.client.transact_write_items.side_effect = ClientError(
            {"Error": {
                "Code": "TransactionCanceledException", "Message": "conflict"
            }}, "TransactWriteItems"
        )
        with self.assertRaises(ClientError):
            self.mod.procesar(self.evento())


if __name__ == "__main__":
    unittest.main()
