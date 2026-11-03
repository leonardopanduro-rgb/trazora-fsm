"""Conversión estricta de Decimal de DynamoDB al responder JSON.

Las cantidades enteras se devuelven como números; las no enteras como
cadenas decimales para no perder precisión al convertirlas a float.
"""


from decimal import Decimal


def decimal_default(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("DynamoDB Decimal no finito")
        if value == value.to_integral_value():
            return int(value)
        return str(value)
    raise TypeError(f"No se puede serializar el tipo {type(value).__name__}")
