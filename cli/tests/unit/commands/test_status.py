from typer.testing import CliRunner

from cli import app, main

runner = CliRunner()


def test_help_lists_status() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "status" in result.stdout


def test_status_placeholder() -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Status: API not configured yet." in result.stdout


def test_status_help() -> None:
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    assert "status" in result.stdout


def test_main_runs() -> None:
    assert callable(main)
