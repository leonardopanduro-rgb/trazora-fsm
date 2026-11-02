import json


def health(event, context):
    """Verifica conectividad; no implementa autenticación."""
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"ok": True, "servicio": "trazora-usuarios"})
    }
