"""Pruebas unitarias locales sin AWS."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "usuarios"))
from security import hash_password, token_hash, verify_password

class SecurityTests(unittest.TestCase):
    def test_password(self):
        password = "ClaveSeguraDePrueba123!"
        password_hash = hash_password(password)
        self.assertTrue(verify_password(password, password_hash))
        self.assertFalse(verify_password("ClaveIncorrecta123!", password_hash))
        self.assertNotEqual(password_hash, hash_password(password))

    def test_hash_tampered(self):
        self.assertFalse(verify_password("UnaClaveLarga123!", "sin-hash"))
        self.assertFalse(verify_password("UnaClaveLarga123!", "pbkdf2_sha256$0$AA==$AA=="))

    def test_token_hash(self):
        self.assertEqual(len(token_hash("token-de-prueba")), 64)
        self.assertNotEqual(token_hash("a"), token_hash("b"))

if __name__ == "__main__":
    unittest.main()
