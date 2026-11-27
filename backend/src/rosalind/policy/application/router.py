"""Route an extracted constraint to an enforcement mechanism.

Routing is decided by the object type and modality, never by the verb alone.
It is deterministic code, not a second LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rosalind.policy.domain.extraction import (
    ConstraintDraft,
    ContentClassObject,
    EmailSelectorObject,
    Modality,
    PropositionObject,
    TopicObject,
)

RouteKind = Literal["access", "confidentiality", "unsupported"]


@dataclass(frozen=True)
class RouteResult:
    kind: RouteKind
    reason: str | None = None


def route(draft: ConstraintDraft) -> RouteResult:
    obj = draft.object

    if isinstance(obj, ContentClassObject):
        return RouteResult(
            "unsupported",
            "content_class_not_supported",
        )

    if isinstance(obj, EmailSelectorObject):
        if draft.modality is Modality.KNOWLEDGE:
            return RouteResult(
                "unsupported",
                "selector_with_knowledge_modality",
            )
        return RouteResult("access")

    if isinstance(obj, (PropositionObject, TopicObject)):
        return RouteResult("confidentiality")

    return RouteResult("unsupported", "unknown_object")
