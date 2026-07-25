"""Symmetric encryption for stored credentials (Blink accounts, SMTP, webhooks).

Fernet (AES-128-CBC + HMAC-SHA256) with a key supplied via ``BLINK_ENCRYPTION_KEY``.
Only ciphertext ever reaches the database.
"""

from cryptography.fernet import Fernet, InvalidToken


class CryptoError(Exception):
    """Raised when encryption or decryption fails."""


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


class SecretBox:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            msg = "BLINK_ENCRYPTION_KEY is not a valid Fernet key (run `make secrets`)"
            raise CryptoError(msg) from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            msg = "ciphertext failed authentication (wrong key or tampered data)"
            raise CryptoError(msg) from exc
