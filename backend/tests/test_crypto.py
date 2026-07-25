"""SecretBox: roundtrip, key validation, tamper detection."""

import pytest

from app.security.crypto import CryptoError, SecretBox, generate_key


def test_roundtrip() -> None:
    box = SecretBox(generate_key())
    assert box.decrypt(box.encrypt("blink-password-123")) == "blink-password-123"


def test_ciphertext_is_not_plaintext() -> None:
    box = SecretBox(generate_key())
    assert "secret" not in box.encrypt("secret")


def test_invalid_key_rejected() -> None:
    with pytest.raises(CryptoError, match="not a valid Fernet key"):
        SecretBox("not-a-key")


def test_wrong_key_fails_decryption() -> None:
    ciphertext = SecretBox(generate_key()).encrypt("data")
    other = SecretBox(generate_key())
    with pytest.raises(CryptoError, match="failed authentication"):
        other.decrypt(ciphertext)


def test_tampered_ciphertext_rejected() -> None:
    key = generate_key()
    box = SecretBox(key)
    ciphertext = box.encrypt("data")
    tampered = ciphertext[:-2] + ("AA" if not ciphertext.endswith("AA") else "BB")
    with pytest.raises(CryptoError):
        box.decrypt(tampered)
