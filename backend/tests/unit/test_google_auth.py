from urllib.parse import parse_qs, urlparse

from rosalind import config
from rosalind.auth import google as google_auth


def _configure(monkeypatch) -> None:
    monkeypatch.setattr(config.settings, "google_client_id", "client-id")
    monkeypatch.setattr(config.settings, "google_client_secret", "client-secret")
    monkeypatch.setattr(
        config.settings,
        "google_redirect_uri",
        "http://localhost:8000/auth/google/callback",
    )
    monkeypatch.setattr(config.settings, "google_auth_prompt", None)


def test_build_authorization_url_requests_offline_access(monkeypatch) -> None:
    _configure(monkeypatch)

    auth_url, code_verifier = google_auth.build_authorization_url(state="state-123")

    query = parse_qs(urlparse(auth_url).query)
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["state"] == ["state-123"]
    assert query["redirect_uri"] == ["http://localhost:8000/auth/google/callback"]
    assert "prompt" not in query
    assert code_verifier


def test_build_authorization_url_generates_code_verifier(monkeypatch) -> None:
    _configure(monkeypatch)

    _, code_verifier = google_auth.build_authorization_url(state="state-123")

    assert len(code_verifier) >= 43


def test_build_authorization_url_omits_prompt_by_default(monkeypatch) -> None:
    _configure(monkeypatch)

    auth_url, _ = google_auth.build_authorization_url(state="state-123")
    assert "prompt=" not in auth_url


def test_build_authorization_url_honors_prompt_config(monkeypatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(config.settings, "google_auth_prompt", "consent")

    auth_url, _ = google_auth.build_authorization_url(state="state-123")
    query = parse_qs(urlparse(auth_url).query)
    assert query["prompt"] == ["consent"]


def test_build_flow_preserves_provided_code_verifier(monkeypatch) -> None:
    _configure(monkeypatch)

    flow = google_auth._build_flow(code_verifier="provided-verifier")

    assert flow.code_verifier == "provided-verifier"
