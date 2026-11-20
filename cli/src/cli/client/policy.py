"""Client for the policy service (``/v1``)."""

from __future__ import annotations

from typing import Any

from cli import config
from cli.client import http


def _api() -> http.ApiClient:
    return http.ApiClient(
        base_url=config.policy_api_url(),
        timeout=config.policy_timeout(),
    )


def list_models() -> dict[str, Any]:
    return _api().get("/v1/policy-models")


def create_draft(prompt: str, model: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"prompt": prompt}
    if model:
        payload["model"] = model
    return _api().post("/v1/policy-drafts", json=payload)


def answer(draft_id: str, constraint_index: int, option_id: str) -> dict[str, Any]:
    return _api().post(
        f"/v1/policy-drafts/{draft_id}/answers",
        json={"constraint_index": constraint_index, "option_id": option_id},
    )


def confirm(draft_id: str, constraint_indexes: list[int] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if constraint_indexes is not None:
        payload["constraint_indexes"] = constraint_indexes
    return _api().post(f"/v1/policy-drafts/{draft_id}/confirm", json=payload)


def delete_draft(draft_id: str) -> None:
    _api().delete(f"/v1/policy-drafts/{draft_id}")


def list_policies() -> list[dict[str, Any]]:
    return _api().get("/v1/policies")


def get_policy(policy_id: str) -> dict[str, Any]:
    return _api().get(f"/v1/policies/{policy_id}")


def set_status(policy_id: str, action: str) -> dict[str, Any]:
    return _api().post(f"/v1/policies/{policy_id}/{action}")
