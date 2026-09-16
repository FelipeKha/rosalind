import pytest
from cryptography.fernet import Fernet

from rosalind import config, security
from rosalind.security import SecurityError


def _set_key(monkeypatch, value: str | None) -> None:
    monkeypatch.setattr(config.settings, "token_encryption_key", value)


def test_encrypt_decrypt_roundtrip(monkeypatch) -> None:
    _set_key(monkeypatch, Fernet.generate_key().decode())

    secret = "super-secret-refresh-token"
    encrypted = security.encrypt_secret(secret)
    assert encrypted != secret
    assert security.decrypt_secret(encrypted) == secret


def test_decrypt_rejects_tampered_token(monkeypatch) -> None:
    _set_key(monkeypatch, Fernet.generate_key().decode())

    encrypted = security.encrypt_secret("secret")
    with pytest.raises(SecurityError):
        security.decrypt_secret(encrypted[:-1] + "A")


def test_encrypt_requires_key(monkeypatch) -> None:
    _set_key(monkeypatch, None)
    with pytest.raises(SecurityError):
        security.encrypt_secret("secret")
