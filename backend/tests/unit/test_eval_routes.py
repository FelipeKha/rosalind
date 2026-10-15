"""HTTP-layer tests for the eval routes (dependencies overridden, no DB)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rosalind.adapters.inbound.http import dependencies
from rosalind.adapters.inbound.http.routes import eval as eval_routes
from rosalind.adapters.outbound.eval.run_store import ParquetRunStore
from rosalind.application.eval.dataset import QuestionRecord
from rosalind.application.services.eval import EvalService
from tests.eval_support import ScriptedExecutor, make_run


class _DummyCatalog:
    def __init__(self, message_ids: dict[str, str] | None = None) -> None:
        self._message_ids = message_ids or {}

    def list_items(self, account_id, import_id=None) -> list[Any]:
        return []

    def existing_item_ids(self, account_id, item_ids):
        return frozenset()

    def resolve_message_ids(self, account_id, message_ids):
        return {
            message_id: item_id
            for message_id, item_id in self._message_ids.items()
            if message_id in message_ids
        }


def _dataset() -> list[dict[str, Any]]:
    return [
        {"id": "q1", "type": "factual", "query": "a", "gold": [{"item_id": "e1"}]},
        {"id": "q2", "type": "factual", "query": "b", "gold": [{"item_id": "e2"}]},
    ]


def _executor() -> ScriptedExecutor:
    runs = {}
    for record in _dataset():
        question = QuestionRecord.model_validate(record)
        gold = [item["item_id"] for item in record["gold"]]
        runs[question.id] = make_run(
            question, lexical=gold, fused=gold, reranked=gold, results=gold
        )
    return ScriptedExecutor(runs)


def _client_with_service(service: EvalService) -> TestClient:
    app = FastAPI()
    app.include_router(eval_routes.router)
    app.dependency_overrides[dependencies.get_current_account] = lambda: (
        SimpleNamespace(id=uuid.uuid4())
    )
    app.dependency_overrides[eval_routes.get_eval_service] = lambda: service
    return TestClient(app)


def _client(tmp_path: Path, catalog: _DummyCatalog | None = None) -> TestClient:
    service = EvalService(
        search_factory=lambda *, overrides, mode: _executor(),
        run_store=ParquetRunStore(tmp_path),
        item_catalog=catalog or _DummyCatalog(),
        account_id=uuid.uuid4(),
    )
    return _client_with_service(service)


def _config() -> dict[str, Any]:
    return {"name": "http", "dataset": "datasets/dev.jsonl"}


def test_list_runs_empty(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/eval/runs")
    assert response.status_code == 200
    assert response.json() == []


def test_validate_dataset(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/eval/validate-dataset", json={"dataset": _dataset()})
    assert response.status_code == 200
    assert response.json() == []


def test_run_streams_and_completes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/eval/run", json={"config": _config(), "dataset": _dataset()}
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    kinds = [event["event"] for event in events]
    assert "run.start" in kinds
    assert kinds.count("question.done") == 2
    complete = next(event for event in events if event["event"] == "run.complete")
    assert complete["metrics"]["overall"]["recall_fused"] == 1.0
    assert client.get("/eval/runs").json() == [complete["run_id"]]

    compare = client.get(
        "/eval/compare",
        params={"run_a": complete["run_id"], "run_b": complete["run_id"]},
    )
    assert compare.status_code == 200
    assert compare.json()[0]["delta"] == 0.0


def test_run_rejects_invalid_dataset(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/eval/run", json={"config": _config(), "dataset": [{"id": "bad"}]}
    )
    assert response.status_code == 422


def test_run_resolves_message_id_gold(tmp_path: Path) -> None:
    raw = {
        "id": "q1",
        "type": "factual",
        "query": "a",
        "gold": [{"message_id": "m1"}],
    }
    resolved = QuestionRecord.model_validate(
        {"id": "q1", "type": "factual", "query": "a", "gold": [{"item_id": "e1"}]}
    )
    executor = ScriptedExecutor(
        {
            "q1": make_run(
                resolved, lexical=["e1"], fused=["e1"], reranked=["e1"], results=["e1"]
            )
        }
    )
    service = EvalService(
        search_factory=lambda *, overrides, mode: executor,
        run_store=ParquetRunStore(tmp_path),
        item_catalog=_DummyCatalog({"m1": "e1"}),
        account_id=uuid.uuid4(),
    )
    client = _client_with_service(service)
    response = client.post("/eval/run", json={"config": _config(), "dataset": [raw]})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    complete = next(event for event in events if event["event"] == "run.complete")
    assert complete["metrics"]["overall"]["recall_fused"] == 1.0


def test_validate_reports_missing_message(tmp_path: Path) -> None:
    client = _client(tmp_path, catalog=_DummyCatalog())
    response = client.post(
        "/eval/validate-dataset",
        json={
            "dataset": [
                {
                    "id": "q1",
                    "type": "factual",
                    "query": "a",
                    "gold": [{"message_id": "unknown"}],
                }
            ]
        },
    )
    assert response.status_code == 200
    assert any(issue["code"] == "missing_message" for issue in response.json())
