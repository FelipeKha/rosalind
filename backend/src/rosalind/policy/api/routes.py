"""Policy service HTTP routes.

Owners only. There is no MCP surface: an agent can never create, edit, or
widen a policy.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status

from rosalind import config
from rosalind.policy.api import schemas
from rosalind.policy.api.deps import AccountDep, ServiceDep
from rosalind.policy.domain.drafts import (
    DraftState,
    PolicyDetail,
    PolicySummary,
)


def _require_enabled() -> None:
    if not config.settings.policy.enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="policy service is disabled",
        )


router = APIRouter(
    prefix="/v1", tags=["policy"], dependencies=[Depends(_require_enabled)]
)


@router.get("/policy-models", response_model=schemas.ModelsResponse)
def list_models(account: AccountDep) -> schemas.ModelsResponse:
    del account
    settings = config.settings.policy
    return schemas.ModelsResponse(
        models=[
            schemas.ModelResponse(
                name=model.name,
                model=model.model,
                quantization=model.quantization,
                enabled=model.enabled,
                is_default=model.name == settings.default_model,
            )
            for model in settings.models
        ],
        default_model=settings.default_model,
    )


@router.post(
    "/policy-drafts",
    response_model=DraftState,
    status_code=status.HTTP_201_CREATED,
)
def create_draft(
    request: schemas.CreateDraftRequest,
    service: ServiceDep,
    account: AccountDep,
) -> DraftState:
    return service.create_draft(account.id, request.prompt, request.model)


@router.post(
    "/policy-drafts/{draft_id}/answers",
    response_model=DraftState,
)
def answer(
    draft_id: uuid.UUID,
    request: schemas.AnswerRequest,
    service: ServiceDep,
    account: AccountDep,
) -> DraftState:
    return service.answer(
        account.id,
        draft_id,
        request.constraint_index,
        request.option_id,
    )


@router.post(
    "/policy-drafts/{draft_id}/confirm",
    response_model=schemas.ConfirmResponse,
)
def confirm(
    draft_id: uuid.UUID,
    request: schemas.ConfirmRequest,
    service: ServiceDep,
    account: AccountDep,
) -> schemas.ConfirmResponse:
    policies = service.confirm(account.id, draft_id, request.constraint_indexes)
    return schemas.ConfirmResponse(policies=policies)


@router.delete(
    "/policy-drafts/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_draft(
    draft_id: uuid.UUID,
    service: ServiceDep,
    account: AccountDep,
) -> Response:
    service.delete_draft(account.id, draft_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/policies", response_model=list[PolicySummary])
def list_policies(service: ServiceDep, account: AccountDep) -> list[PolicySummary]:
    return service.list_policies(account.id)


@router.get("/policies/{policy_id}", response_model=PolicyDetail)
def get_policy(
    policy_id: uuid.UUID,
    service: ServiceDep,
    account: AccountDep,
) -> PolicyDetail:
    return service.get_policy(account.id, policy_id)


def _set_status(
    policy_id: uuid.UUID,
    new_status: str,
    service: ServiceDep,
    account: AccountDep,
) -> PolicySummary:
    return service.set_policy_status(account.id, policy_id, new_status)


@router.post("/policies/{policy_id}/pause", response_model=PolicySummary)
def pause_policy(
    policy_id: uuid.UUID,
    service: ServiceDep,
    account: AccountDep,
) -> PolicySummary:
    return _set_status(policy_id, "paused", service, account)


@router.post("/policies/{policy_id}/resume", response_model=PolicySummary)
def resume_policy(
    policy_id: uuid.UUID,
    service: ServiceDep,
    account: AccountDep,
) -> PolicySummary:
    detail = service.get_policy(account.id, policy_id)
    status = "active" if detail.policy_type == "access" else "pending_enforcement"
    return _set_status(policy_id, status, service, account)


@router.post("/policies/{policy_id}/revoke", response_model=PolicySummary)
def revoke_policy(
    policy_id: uuid.UUID,
    service: ServiceDep,
    account: AccountDep,
) -> PolicySummary:
    return _set_status(policy_id, "revoked", service, account)
