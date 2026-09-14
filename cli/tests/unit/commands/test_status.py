from typer.testing import CliRunner

from cli import app, client, main

runner = CliRunner()


def test_help_lists_status() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "status" in result.stdout


def test_status_reports_healthy(monkeypatch) -> None:
    monkeypatch.setattr(client, "get_health", lambda: {"status": "ok"})
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Backend: healthy" in result.stdout


def test_status_reports_unreachable(monkeypatch) -> None:
    def raise_error() -> dict[str, str]:
        raise client.ApiClientError("unable to reach the Rosalind backend")

    monkeypatch.setattr(client, "get_health", raise_error)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "Backend: unreachable" in result.stderr


def test_status_help() -> None:
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    assert "status" in result.stdout


def test_main_runs() -> None:
    assert callable(main)
