"""The app lifespan warms the search models at startup."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rosalind.adapters.inbound.http import app as app_module


def test_lifespan_warms_search_models(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        app_module.composition,
        "warm_search_models",
        lambda: calls.append(True),
    )

    with TestClient(app_module.app):
        pass

    assert calls == [True]
