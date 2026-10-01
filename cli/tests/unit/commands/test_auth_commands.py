"""Unit tests for `rosalind auth whoami`."""

from __future__ import annotations

from typer.testing import CliRunner

from cli import app
from cli.commands import auth as auth_commands

runner = CliRunner()


def test_whoami_prints_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_commands.account_client,
        "whoami",
        lambda: {
            "account_id": "abc",
            "email": "jane@example.com",
            "given_name": "Jane",
            "family_name": "Doe",
        },
    )

    result = runner.invoke(app, ["auth", "whoami"])

    assert result.exit_code == 0
    assert "Account: abc" in result.stdout
    assert "jane@example.com" in result.stdout
    assert "Jane Doe" in result.stdout


def test_whoami_not_signed_in(monkeypatch) -> None:
    def raise_error() -> dict:
        raise auth_commands.ApiClientError("request failed (401)")

    monkeypatch.setattr(auth_commands.account_client, "whoami", raise_error)

    result = runner.invoke(app, ["auth", "whoami"])

    assert result.exit_code == 1
    assert "Not signed in" in result.stderr
