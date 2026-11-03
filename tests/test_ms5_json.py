"""Pruebas sin conexión a AWS para serialización JSON de MS5."""
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "partes"))
from json_utils import decimal_default


class TestPartesJson(unittest.TestCase):
    def test_version_desde_dynamodb(self):
        datos = {"parte": {"version": Decimal("1"), "estado": "BORRADOR"}}
        convertido = json.loads(json.dumps(datos, default=decimal_default))
        self.assertEqual(convertido["parte"]["version"], 1)
        self.assertIsInstance(convertido["parte"]["version"], int)

    def test_size_bytes_desde_dynamodb(self):
        datos = {"evidencia": {"size_bytes": Decimal("68"), "estado": "CONFIRMADA"}}
        convertido = json.loads(json.dumps(datos, default=decimal_default))
        self.assertEqual(convertido["evidencia"]["size_bytes"], 68)

    def test_decimal_fraccionario_sin_perdida(self):
        self.assertEqual(
            json.loads(json.dumps({"valor": Decimal("12.345")}, default=decimal_default)),
            {"valor": "12.345"},
        )

    def test_tipos_no_soportados(self):
        with self.assertRaises(TypeError):
            json.dumps({"valor": object()}, default=decimal_default)


if __name__ == "__main__":
    unittest.main()
