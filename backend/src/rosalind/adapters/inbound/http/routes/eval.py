"""Eval HTTP surface (mounted only when ``eval.enabled``).

Thin inbound adapter: validates/eval-parses the request, calls the composed
``EvalService``, and streams or returns the result. No SQL or pipeline wiring.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from rosalind import config
from rosalind.adapters import composition
from rosalind.adapters.inbound.http.dependencies import AccountDep, get_current_account
from rosalind.adapters.inbound.http.schemas import eval as schemas
from rosalind.application.eval.config import parse_config
from rosalind.application.eval.dataset import QuestionRecord

router = APIRouter(
    prefix="/eval",
    tags=["eval"],
    dependencies=[Depends(get_current_account)],
)


def get_eval_service(account: AccountDep) -> Any:
    if not config.settings.eval.enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="eval mode is disabled"
        )
    return composition.build_eval_service(account.id)


EvalServiceDep = Annotated[Any, Depends(get_eval_service)]


@router.post("/run")
def run(
    request: schemas.EvalRunRequest,
    service: EvalServiceDep,
) -> StreamingResponse:
    """Run an experiment, streaming newline-delimited JSON progress events."""
    experiment = _parse_config(request.config)
    records = _parse_records(request.dataset)
    known = _frozen(request.known_item_ids)
    chunked = _frozen(request.chunked_item_ids)

    def generate():
        for event in service.iter_run(
            experiment, records, known_item_ids=known, chunked_item_ids=chunked
        ):
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.get("/runs")
def list_runs(service: EvalServiceDep) -> list[str]:
    return list(service.list_runs())


@router.get("/runs/{run_id}")
def get_run(run_id: str, service: EvalServiceDep) -> schemas.EvalRunDirResponse:
    try:
        return schemas.EvalRunDirResponse(
            run_id=run_id,
            manifest=service._run_store.read_manifest(run_id),
            metrics=service._run_store.read_metrics(run_id),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no such run: {run_id}"
        ) from exc


@router.get("/compare")
def compare(
    service: EvalServiceDep,
    run_a: str,
    run_b: str,
) -> list[dict[str, Any]]:
    try:
        deltas = service.compare(run_a, run_b)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return [_delta_to_dict(delta) for delta in deltas]


@router.post("/validate-dataset")
def validate_dataset(
    request: schemas.EvalValidateRequest,
    service: EvalServiceDep,
) -> list[schemas.EvalIssueResponse]:
    records = _parse_records(request.dataset)
    issues = service.validate(records, known_item_ids=_frozen(request.known_item_ids))
    return [
        schemas.EvalIssueResponse(
            level=issue.level,
            code=issue.code,
            message=issue.message,
            question_id=issue.question_id,
        )
        for issue in issues
    ]


@router.post("/generate-questions")
def generate_questions(
    request: schemas.EvalGenerateRequest,
    service: EvalServiceDep,
) -> list[dict[str, Any]]:
    try:
        records = service.generate(
            request.mailbox,
            split=request.split,
            include_trash_spam=request.include_trash_spam,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return [record.model_dump(mode="json") for record in records]


@router.get("/items")
def list_items(
    service: EvalServiceDep,
    account: AccountDep,
    import_id: uuid.UUID | None = None,
) -> list[schemas.EvalItemResponse]:
    items = service.list_items(account.id, import_id)
    return [
        schemas.EvalItemResponse(
            item_id=item.item_id,
            subject=item.subject,
            sender=item.sender,
            occurred_at=item.occurred_at,
            has_attachments=item.has_attachments,
            is_trash_or_spam=item.is_trash_or_spam,
        )
        for item in items
    ]


def _parse_config(raw: dict[str, Any]):
    try:
        return parse_config(raw)
    except (TypeError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _parse_records(raw: list[dict[str, Any]]) -> list[QuestionRecord]:
    records: list[QuestionRecord] = []
    for index, item in enumerate(raw):
        try:
            records.append(QuestionRecord.model_validate(item))
        except (TypeError, ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"dataset item {index}: {exc}",
            ) from exc
    return records


def _frozen(values: list[str] | None) -> frozenset[str] | None:
    return frozenset(values) if values is not None else None


def _delta_to_dict(delta: Any) -> dict[str, Any]:
    return {
        "metric": delta.metric,
        "a": delta.a,
        "b": delta.b,
        "delta": delta.delta,
        "ci_low": delta.ci_low,
        "ci_high": delta.ci_high,
        "p_value": delta.p_value,
        "pairs": delta.pairs,
    }
