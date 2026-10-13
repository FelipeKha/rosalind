"""Eval-mode gating: the eval surface exists only when enabled."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException

from rosalind import config
from rosalind.adapters.inbound.http.app import app
from rosalind.adapters.inbound.http.routes import eval as eval_routes
from rosalind.domain.account import Account


def _account() -> Account:
    return cast(Account, SimpleNamespace(id=uuid.uuid4()))


def test_eval_disabled_by_default() -> None:
    assert config.settings.eval.enabled is False


def test_eval_routes_absent_when_disabled() -> None:
    paths = set(app.openapi().get("paths", {}))
    assert not any(path.startswith("/eval") for path in paths)


def test_get_eval_service_rejects_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(config.settings.eval, "enabled", False)
    with pytest.raises(HTTPException) as excinfo:
        eval_routes.get_eval_service(_account())
    assert excinfo.value.status_code == 404


def test_get_eval_service_builds_when_enabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config.settings.eval, "enabled", True)
    monkeypatch.setattr(config.settings.eval, "runs_dir", tmp_path / "runs")
    service = eval_routes.get_eval_service(_account())
    assert service is not None


def test_eval_router_exposes_expected_paths() -> None:
    paths = {getattr(route, "path", None) for route in eval_routes.router.routes}
    assert "/eval/run" in paths
    assert "/eval/compare" in paths
    assert "/eval/validate-dataset" in paths
    assert "/eval/items" in paths
