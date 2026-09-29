"""Unit tests for the Keycloak JWKS JWT verifier."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from rosalind.adapters.outbound.keycloak.jwt import KeycloakJwtVerifier

ISSUER = "http://localhost:8080/realms/rosalind"
AUDIENCE = "rosalind"


class _FakeSigningKey:
    def __init__(self, public_key: Any):
        self.key = public_key


class _FakeJWKS:
    def __init__(self, public_key: Any):
        self._key = public_key

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(self._key)


def _private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _public_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _token(
    private_key: rsa.RSAPrivateKey,
    *,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    subject: str = "user-123",
    exp: datetime | None = None,
) -> str:
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "exp": exp or (datetime.now(UTC) + timedelta(minutes=5)),
            "scope": "openid",
        },
        private_key,
        algorithm="RS256",
    )


def _verifier(monkeypatch, private_key: rsa.RSAPrivateKey) -> KeycloakJwtVerifier:
    verifier = KeycloakJwtVerifier()
    monkeypatch.setattr(verifier, "_jwks", _FakeJWKS(_public_pem(private_key).decode()))
    return verifier


def test_verifies_valid_token(monkeypatch) -> None:
    private_key = _private_key()
    verifier = _verifier(monkeypatch, private_key)
    token = _token(private_key)

    verified = verifier.verify(token)

    assert verified is not None
    assert verified.subject == "user-123"
    assert verified.issuer == ISSUER
    assert verified.scopes == ["openid"]


def test_rejects_tampered_token(monkeypatch) -> None:
    private_key = _private_key()
    verifier = _verifier(monkeypatch, private_key)
    token = _token(private_key, subject="user-123")

    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload[:-2]}xx.{signature}"

    assert verifier.verify(tampered) is None


def test_rejects_wrong_issuer(monkeypatch) -> None:
    private_key = _private_key()
    verifier = _verifier(monkeypatch, private_key)
    token = _token(private_key, issuer="http://evil.example/realms/rosalind")

    assert verifier.verify(token) is None


def test_rejects_wrong_audience(monkeypatch) -> None:
    private_key = _private_key()
    verifier = _verifier(monkeypatch, private_key)
    token = _token(private_key, audience="some-other-api")

    assert verifier.verify(token) is None


def test_rejects_expired_token(monkeypatch) -> None:
    private_key = _private_key()
    verifier = _verifier(monkeypatch, private_key)
    token = _token(private_key, exp=datetime.now(UTC) - timedelta(minutes=5))

    assert verifier.verify(token) is None
