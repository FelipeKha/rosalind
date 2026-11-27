"""Fernet-backed secret box using the platform encryption key."""

from __future__ import annotations

from rosalind.security import decrypt_secret, encrypt_secret


class FernetSecretBox:
    def encrypt(self, value: str) -> str:
        return encrypt_secret(value)

    def decrypt(self, token: str) -> str:
        return decrypt_secret(token)
