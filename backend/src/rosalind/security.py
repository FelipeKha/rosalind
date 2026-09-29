"""Encryption helpers for at-rest secrets (e.g. OAuth tokens)."""

from cryptography.fernet import Fernet, InvalidToken

from rosalind import config


class SecurityError(Exception):
    """Raised when secrets cannot be encrypted or decrypted."""


def _fernet() -> Fernet:
    key = config.settings.token_encryption_key
    if not key:
        raise SecurityError(
            "ROSALIND_TOKEN_ENCRYPTION_KEY is not configured; "
            "generate one with `python -c 'from cryptography.fernet import "
            "Fernet; print(Fernet.generate_key().decode())'`"
        )
    return Fernet(key.encode("utf-8"))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SecurityError("failed to decrypt stored secret") from exc
