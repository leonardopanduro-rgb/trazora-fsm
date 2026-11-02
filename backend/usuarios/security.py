"""Helpers de seguridad PBKDF2-SHA256 (stdlib Python)."""
import base64
import binascii
import hashlib
import hmac
import secrets

ITERATIONS = 600_000

def hash_password(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("La contraseña debe tener entre 12 y 128 caracteres")
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(derived).decode()
    )

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations, encoded_salt, encoded_derived = stored_hash.split("$")
        count = int(iterations)
        if scheme != "pbkdf2_sha256" or not ITERATIONS <= count <= 2_000_000 or not isinstance(password, str):
            return False
        salt = base64.b64decode(encoded_salt, validate=True)
        expected = base64.b64decode(encoded_derived, validate=True)
        if len(salt) < 16 or len(expected) != 32:
            return False
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, count)
        return hmac.compare_digest(derived, expected)
    except (ValueError, AttributeError, TypeError, binascii.Error):
        return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
