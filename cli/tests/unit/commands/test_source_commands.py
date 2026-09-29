from typer.testing import CliRunner

from cli import app
from cli.commands import source as source_module

runner = CliRunner()


def _summary(source_id: str = "s-1") -> dict[str, object]:
    return {
        "source_id": source_id,
        "name": "google-personal",
        "provider": "google",
        "display_name": "Jane Doe",
        "status": "connected",
    }


def test_list_sources(monkeypatch) -> None:
    monkeypatch.setattr(source_module.client, "list_sources", lambda: [_summary()])
    result = runner.invoke(app, ["source", "list"])
    assert result.exit_code == 0
    assert "google-personal" in result.stdout


def test_list_sources_empty(monkeypatch) -> None:
    monkeypatch.setattr(source_module.client, "list_sources", list)
    result = runner.invoke(app, ["source", "list"])
    assert result.exit_code == 0
    assert "No sources found" in result.stdout


def test_create_source(monkeypatch) -> None:
    monkeypatch.setattr(
        source_module.client,
        "create_source",
        lambda provider, name: {**_summary(), "status": "disconnected"},
    )
    result = runner.invoke(
        app, ["source", "create", "google", "--name", "google-personal"]
    )
    assert result.exit_code == 0
    assert "Created source" in result.stdout


def test_connect_prints_url_and_polls(monkeypatch) -> None:
    monkeypatch.setattr(
        source_module.client,
        "connect",
        lambda provider, name: {"auth_url": "https://example.com/auth", "state": "s1"},
    )
    monkeypatch.setattr(source_module, "_poll_status", lambda state: None)

    result = runner.invoke(
        app,
        ["source", "connect", "google", "--name", "google-personal", "--no-browser"],
    )

    assert result.exit_code == 0
    assert "https://example.com/auth" in result.stdout


def test_disconnect_by_name_resolves_id(monkeypatch) -> None:
    monkeypatch.setattr(source_module.client, "list_sources", lambda: [_summary()])
    disconnected: list[str] = []

    def fake_disconnect(source_id: str) -> dict[str, object]:
        disconnected.append(source_id)
        return {"status": "disconnected", "revoked": True}

    monkeypatch.setattr(source_module.client, "disconnect", fake_disconnect)

    result = runner.invoke(app, ["source", "disconnect", "google-personal"])

    assert result.exit_code == 0
    assert disconnected == ["s-1"]
    assert "Disconnected" in result.stdout


def test_disconnect_already_disconnected(monkeypatch) -> None:
    monkeypatch.setattr(source_module.client, "list_sources", lambda: [_summary()])
    monkeypatch.setattr(
        source_module.client,
        "disconnect",
        lambda source_id: {"status": "already_disconnected", "revoked": False},
    )

    result = runner.invoke(app, ["source", "disconnect", "google-personal"])

    assert result.exit_code == 0
    assert "not connected" in result.stdout


def test_disconnect_error(monkeypatch) -> None:
    monkeypatch.setattr(source_module.client, "list_sources", lambda: [_summary()])

    def raise_error(source_id: str) -> dict[str, object]:
        raise source_module.ApiClientError("boom")

    monkeypatch.setattr(source_module.client, "disconnect", raise_error)
    result = runner.invoke(app, ["source", "disconnect", "google-personal"])
    assert result.exit_code == 1
    assert "Failed to disconnect" in result.stderr
