"""Client for the eval resource (``/eval``). Eval mode only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from cli.client import http


def run_experiment(
    config: dict[str, Any],
    dataset: list[dict[str, Any]],
    *,
    known_item_ids: list[str] | None = None,
    chunked_item_ids: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    payload: dict[str, Any] = {
        "config": config,
        "dataset": dataset,
        "known_item_ids": known_item_ids,
        "chunked_item_ids": chunked_item_ids,
    }
    for line in http.api.stream_post("/eval/run", json=payload):
        yield json.loads(line)


def list_runs() -> list[str]:
    return http.api.get("/eval/runs")


def get_run(run_id: str) -> dict[str, Any]:
    return http.api.get(f"/eval/runs/{run_id}")


def compare(run_a: str, run_b: str) -> list[dict[str, Any]]:
    return http.api.get("/eval/compare", params={"run_a": run_a, "run_b": run_b})


def validate_dataset(
    dataset: list[dict[str, Any]],
    *,
    known_item_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    return http.api.post(
        "/eval/validate-dataset",
        json={"dataset": dataset, "known_item_ids": known_item_ids},
    )


def generate_questions(
    mailbox: str,
    *,
    split: str = "dev",
    include_trash_spam: bool = False,
) -> list[dict[str, Any]]:
    return http.api.post(
        "/eval/generate-questions",
        json={
            "mailbox": mailbox,
            "split": split,
            "include_trash_spam": include_trash_spam,
        },
    )


def list_items(import_id: str | None = None) -> list[dict[str, Any]]:
    params = {"import_id": import_id} if import_id else None
    return http.api.get("/eval/items", params=params)
