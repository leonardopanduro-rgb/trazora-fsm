"""Pruebas locales de los consumidores SNS/SQS de Trazora, sin AWS real."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PARTE = "11111111-2222-3333-4444-555555555555"
VISITA = "22222222-3333-4444-5555-666666666666"
ORDEN = "33333333-4444-5555-6666-777777777777"
TECNICO = "44444444-5555-6666-7777-888888888888"
EVENTO = "55555555-6666-7777-8888-999999999999"
TENANT = "CLIMALIMA"
TOPICO = "arn:aws:sns:us-east-1:000000000000:trazora-fsm-eventos-dev"


def importar(servicio):
    archivo = ROOT / "backend" / servicio / "consumidor.py"
    spec = importlib.util.spec_from_file_location(f"eda_test_{servicio}", archivo)
    mod = importlib.util.module_from_spec(spec)
    env = {
        "ORDENES_TABLE": "ordenes-test",
        "AGENDA_TABLE": "agenda-test",
        "SQS_ORDENES_ARN": "arn:aws:sqs:us-east-1:000000000000:ordenes",
        "SQS_AGENDA_ARN": "arn:aws:sqs:us-east-1:000000000000:agenda",
        "EVENTOS_TOPIC_ARN": TOPICO,
        "AWS_REGION": "us-east-1",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        with mock.patch("boto3.resource"), mock.patch("boto3.client"):
            spec.loader.exec_module(mod)
    return mod


def evento(tipo="ParteFinalizado", tenant=TENANT, resultado="RESUELTO"):
    return {
        "event_id": EVENTO,
        "event_type": tipo,
        "schema_version": 1,
        "tenant_id": tenant,
        "aggregate_type": "PARTE" if tipo == "ParteFinalizado" else "VISITA",
        "aggregate_id": PARTE if tipo == "ParteFinalizado" else VISITA,
        "aggregate_version": 3,
        "occurred_at": "2026-11-06T17:00:00Z",
        "correlation_id": VISITA,
        "data": {
            "visita_id": VISITA, "orden_id": ORDEN,
            "parte_id": PARTE, "resultado": resultado,
        },
    }


class OrdenesTest(unittest.TestCase):
    def setUp(self):
        self.mod = importar("ordenes")
        self.table = mock.Mock()
        self.client = mock.Mock()
        self.mod.TABLE = self.table
        self.mod.DYNAMODB = self.client
        self.orden = {
            "tenant_id": TENANT, "orden_id": ORDEN, "estado": "ABIERTA",
        }
        def get_item(*, Key, ConsistentRead):
            if Key["SK"].startswith("ORDEN#"):
                return {"Item": dict(self.orden)}
            return {}
        self.table.get_item.side_effect = get_item

    def test_parte_solo_registra_historial_no_cambia_estado(self):
        self.assertEqual(self.mod.procesar(evento()), "procesado")
        acciones = self.client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(acciones), 2)
        self.assertTrue(all("Put" in a for a in acciones))
        self.assertIn("HISTORIAL#", acciones[0]["Put"]["Item"]["SK"]["S"])
        self.assertEqual(acciones[0]["Put"]["Item"]["resultado"]["S"], "RESUELTO")

    def test_solo_visita_completada_cambia_orden(self):
        self.assertEqual(self.mod.procesar(evento("VisitaCompletada")), "procesado")
        acciones = self.client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(acciones), 3)
        cambio = acciones[0]["Update"]
        self.assertEqual(cambio["ExpressionAttributeValues"][":nuevo"], {
            "S": "PENDIENTE_DE_CIERRE"
        })

    def test_no_resuelto_deja_orden_abierta(self):
        self.mod.procesar(evento("VisitaCompletada", resultado="REQUIERE_REVISITA"))
        cambio = self.client.transact_write_items.call_args.kwargs["TransactItems"][0]["Update"]
        self.assertEqual(cambio["ExpressionAttributeValues"][":nuevo"], {"S": "ABIERTA"})

    def test_evento_antiguo_no_revierte_estado(self):
        self.orden["ultimo_visita_completada_en"] = "2026-11-07T17:00:00.000000+00:00"
        self.assertEqual(self.mod.procesar(evento("VisitaCompletada")), "obsoleto")
        acciones = self.client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(acciones), 2)

    def test_no_acepta_orden_ajena(self):
        self.orden["tenant_id"] = "FRIOSUR"
        with self.assertRaises(ValueError):
            self.mod.procesar(evento())
        self.client.transact_write_items.assert_not_called()

    def test_reintento_duplicado_no_escribe(self):
        e = evento()
        digest = hashlib.sha256(json.dumps(
            e, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        self.table.get_item.side_effect = lambda **kwargs: {
            "Item": {"payload_sha256": digest}
        } if kwargs["Key"]["SK"].startswith("INBOX#") else {
            "Item": dict(self.orden)
        }
        self.assertEqual(self.mod.procesar(e), "duplicado")
        self.client.transact_write_items.assert_not_called()


class AgendaTest(unittest.TestCase):
    def setUp(self):
        self.mod = importar("agenda")
        self.table = mock.Mock()
        self.client = mock.Mock()
        self.sns = mock.Mock()
        self.mod.TABLE = self.table
        self.mod.DYNAMODB = self.client
        self.mod.SNS = self.sns
        self.e = evento()
        self.visita = {
            "tenant_id": TENANT, "visita_id": VISITA,
            "orden_id": ORDEN, "tecnico_id": TECNICO,
            "estado": "EN_ATENCION", "version": 2,
            "inicio": "2026-11-06T15:00:00Z",
            "fin": "2026-11-06T16:00:00Z",
        }
        def get_item(*, Key, ConsistentRead):
            if Key["SK"].startswith("VISITA#"):
                return {"Item": dict(self.visita)}
            if Key["SK"].startswith("OUTBOX#"):
                return {"Item": {
                    **Key, "entity_type": "OUTBOX", "estado": "PENDIENTE",
                    "tenant_id": TENANT,
                    "event_id": self.mod.id_completada(self.e),
                    "payload": {
                        "event_id": self.mod.id_completada(self.e),
                        "tenant_id": TENANT, "event_type": "VisitaCompletada",
                    },
                }}
            return {}
        self.table.get_item.side_effect = get_item

    def test_transaccion_inbox_outbox_y_reservas(self):
        estado, llave = self.mod.procesar(self.e)
        self.assertEqual(estado, "finalizado")
        self.assertTrue(llave["SK"].startswith("OUTBOX#"))
        acciones = self.client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(acciones), 6)  # visita, 2 bloques, control, INBOX, OUTBOX
        self.assertEqual(acciones[0]["Update"]["ExpressionAttributeValues"][":finalizada"],
                         {"S": "FINALIZADA"})
        self.assertEqual(acciones[-1]["Put"]["Item"]["event_type"]["S"],
                         "VisitaCompletada")

    def test_publica_sns_tras_confirmar(self):
        raw = {"Records": [{
            "eventSource": "aws:sqs", "eventSourceARN": self.mod.SQS_ARN,
            "messageId": "msg1", "body": json.dumps(self.e),
        }]}
        self.assertEqual(self.mod.lambda_handler(raw, None)["procesados"], 1)
        self.sns.publish.assert_called_once()
        self.assertEqual(self.sns.publish.call_args.kwargs["TopicArn"], TOPICO)
        self.table.update_item.assert_called_once()

    def test_evento_ajeno_no_modifica_visita(self):
        self.visita["tenant_id"] = "FRIOSUR"
        with self.assertRaises(ValueError):
            self.mod.procesar(self.e)
        self.client.transact_write_items.assert_not_called()

    def test_publicacion_fallida_reintenta_sqs(self):
        self.sns.publish.side_effect = RuntimeError("SNS temporalmente caido")
        raw = {"Records": [{
            "eventSource": "aws:sqs", "eventSourceARN": self.mod.SQS_ARN,
            "messageId": "msg1", "body": json.dumps(self.e),
        }]}
        with self.assertRaises(RuntimeError):
            self.mod.lambda_handler(raw, None)
        self.client.transact_write_items.assert_called_once()
        self.table.update_item.assert_not_called()


if __name__ == "__main__":
    unittest.main()
