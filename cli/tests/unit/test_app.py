"""Tests for global CLI options and config-file error handling."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from cli import app

runner = CliRunner()


def test_invalid_config_exits_with_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- not\n- a\n- mapping\n")
    monkeypatch.setenv("ROSALIND_CONFIG", str(bad))

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 2
    assert "invalid configuration" in result.stderr


def test_missing_profile_exits_with_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["--profile", "eval", "status"])

    assert result.exit_code == 2
    assert "profile config not found" in result.stderr


def test_profile_selects_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "eval.yaml").write_text("api_url: http://localhost:1234\n")
    captured: dict[str, str] = {}

    def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        return httpx.Response(
            200, json={"status": "ok"}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr("cli.client.http.httpx.request", fake_request)

    result = runner.invoke(app, ["--profile", "eval", "status"])

    assert result.exit_code == 0
    assert captured["url"] == "http://localhost:1234/health"
