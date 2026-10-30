"""Request/response models for the eval HTTP surface (eval mode only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "EvalGenerateRequest",
    "EvalIssueResponse",
    "EvalRunRequest",
    "EvalRunSummaryResponse",
    "EvalValidateRequest",
]


class EvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any]
    dataset: list[dict[str, Any]]
    known_item_ids: list[str] | None = None
    chunked_item_ids: list[str] | None = None


class EvalValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: list[dict[str, Any]]
    known_item_ids: list[str] | None = None


class EvalGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mailbox: str
    split: Literal["dev", "test"] = "dev"
    include_trash_spam: bool = False


class EvalRunSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    metrics: dict[str, Any]
    warnings: list[str]
    location: str | None = None


class EvalIssueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["error", "warning"]
    code: str
    message: str
    question_id: str | None = None


class EvalItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    subject: str | None = None
    sender: str | None = None
    occurred_at: datetime | None = None
    has_attachments: bool
    is_trash_or_spam: bool


class EvalRunDirResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    manifest: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
