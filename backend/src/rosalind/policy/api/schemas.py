"""HTTP request/response schemas for the policy service."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from rosalind.policy.domain.drafts import PolicySummary


class CreateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=4000)
    model: str | None = None


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_index: int = Field(ge=0)
    option_id: str = Field(min_length=1)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_indexes: list[int] | None = None


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    model: str
    quantization: str | None
    enabled: bool
    is_default: bool


class ModelsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[ModelResponse]
    default_model: str | None


class ConfirmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policies: list[PolicySummary]
