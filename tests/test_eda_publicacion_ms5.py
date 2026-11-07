"""Pruebas locales de publicacion SNS directa desde MS5, sin AWS."""
import importlib.util
import json
import os
from pathlib import Path
from decimal import Decimal
import sys
import unittest
from unittest import mock

OUTBOX = {
    "PK": "TENANT#CLIMALIMA",
    "SK": "OUTBOX#55555555-6666-7777-8888-999999999999",
    "entity_type": "OUTBOX",
    "tenant_id": "CLIMALIMA",
    "event_id": "55555555-6666-7777-8888-999999999999",
    "event_type": "ParteFinalizado",
    "estado": "PENDIENTE",
    "payload": {
        "event_id": "55555555-6666-7777-8888-999999999999",
        "event_type": "ParteFinalizado",
        "tenant_id": "CLIMALIMA",
        "data": {"orden_id": "11111111-2222-3333-4444-555555555555"},
    },
}


def importar_handler():
    directory = Path(__file__).resolve().parents[1] / "backend" / "partes"
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location("ms5_eda_publisher_test", directory / "handler.py")
    modulo = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {
        "PARTES_TABLE": "partes-test",
        "EVIDENCIAS_BUCKET": "evidencias-test",
        "AGENDA_API_BASE": "https://agenda.example.test/dev",
        "EVENTOS_TOPIC_ARN": "arn:aws:sns:us-east-1:000000000000:trazora-fsm-eventos-dev",
        "AWS_REGION": "us-east-1",
    }, clear=True), mock.patch("boto3.resource"), mock.patch("boto3.client"):
        spec.loader.exec_module(modulo)
    return modulo


class PublicacionMS5Test(unittest.TestCase):
    def setUp(self):
        self.mod = importar_handler()
        self.tabla = mock.Mock()
        self.sns = mock.Mock()
        self.mod.TABLE = self.tabla
        self.mod.SNS = self.sns

    def test_sns_pub_y_marca_publicado(self):
        estado = self.mod.publicar_outbox(dict(OUTBOX))
        self.assertEqual(estado, "PUBLICADO")
        mensaje = json.loads(self.sns.publish.call_args.kwargs["Message"])
        self.assertEqual(mensaje["event_type"], "ParteFinalizado")
        self.assertEqual(mensaje["event_id"], OUTBOX["event_id"])
        self.tabla.update_item.assert_called_once()

    def test_publica_agregate_version_decimal_como_entero(self):
        outbox = {
            **OUTBOX,
            "payload": {**OUTBOX["payload"], "aggregate_version": Decimal("3")},
        }
        estado = self.mod.publicar_outbox(outbox)
        self.assertEqual(estado, "PUBLICADO")
        mensaje = json.loads(self.sns.publish.call_args.kwargs["Message"])
        self.assertEqual(mensaje["aggregate_version"], 3)
        self.assertIs(type(mensaje["aggregate_version"]), int)

    def test_falla_sns_conserva_pendiente(self):
        self.sns.publish.side_effect = RuntimeError("Sin autorizacion o SNS no disponible")
        estado = self.mod.publicar_outbox(dict(OUTBOX))
        self.assertEqual(estado, "PENDIENTE_PUBLICACION")
        self.tabla.update_item.assert_not_called()

    def test_falla_al_marcar_conserva_pendiente(self):
        self.tabla.update_item.side_effect = RuntimeError("DynamoDB sin respuesta")
        estado = self.mod.publicar_outbox(dict(OUTBOX))
        self.assertEqual(estado, "PENDIENTE_PUBLICACION")
        self.sns.publish.assert_called_once()

    def test_outbox_publicado_no_republica(self):
        item = dict(OUTBOX)
        item["estado"] = "PUBLICADO"
        self.assertEqual(self.mod.publicar_outbox(item), "PUBLICADO")
        self.sns.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
