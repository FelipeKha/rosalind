from typer.testing import CliRunner

from cli import app
from cli.commands import google_commands

runner = CliRunner()


def test_connect_prints_url_and_polls(monkeypatch) -> None:
    monkeypatch.setattr(
        google_commands.client,
        "connect_google",
        lambda: {"auth_url": "https://example.com/auth", "state": "s1"},
    )
    monkeypatch.setattr(google_commands, "_poll_status", lambda state: None)

    result = runner.invoke(app, ["google", "connect", "--no-browser"])

    assert result.exit_code == 0
    assert "https://example.com/auth" in result.stdout


def test_connect_reports_backend_error(monkeypatch) -> None:
    monkeypatch.setattr(
        google_commands.client,
        "connect_google",
        lambda: (_ for _ in ()).throw(google_commands.client.ApiClientError("boom")),
    )

    result = runner.invoke(app, ["google", "connect", "--no-browser"])

    assert result.exit_code == 1
    assert "Failed to start Google authorization" in result.stderr


def test_import_profile_prints_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        google_commands.client,
        "import_google_profile",
        lambda: {"status": "success", "display_name": "Jane Doe", "account": "12345"},
    )

    result = runner.invoke(app, ["google", "import", "profile"])

    assert result.exit_code == 0
    assert "Imported Google profile for Jane Doe." in result.stdout


def test_import_profile_reports_backend_error(monkeypatch) -> None:
    monkeypatch.setattr(
        google_commands.client,
        "import_google_profile",
        lambda: (_ for _ in ()).throw(google_commands.client.ApiClientError("boom")),
    )

    result = runner.invoke(app, ["google", "import", "profile"])

    assert result.exit_code == 1
    assert "Failed to import Google profile" in result.stderr


def test_disconnect_prints_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        google_commands.client,
        "disconnect_google",
        lambda: {"status": "disconnected", "revoked": True},
    )

    result = runner.invoke(app, ["google", "disconnect"])

    assert result.exit_code == 0
    assert "Disconnected from Google." in result.stdout


def test_disconnect_already_disconnected(monkeypatch) -> None:
    monkeypatch.setattr(
        google_commands.client,
        "disconnect_google",
        lambda: {"status": "already_disconnected", "revoked": False},
    )

    result = runner.invoke(app, ["google", "disconnect"])

    assert result.exit_code == 0
    assert "Google is not connected." in result.stdout


def test_disconnect_reports_backend_error(monkeypatch) -> None:
    monkeypatch.setattr(
        google_commands.client,
        "disconnect_google",
        lambda: (_ for _ in ()).throw(google_commands.client.ApiClientError("boom")),
    )

    result = runner.invoke(app, ["google", "disconnect"])

    assert result.exit_code == 1
    assert "Failed to disconnect Google" in result.stderr
