from __future__ import annotations

from rosalind.policy.application.router import route
from rosalind.policy.domain.extraction import (
    ConstraintDraft,
    ContentClassObject,
    EmailSelectorObject,
    Modality,
    PropositionObject,
    TopicObject,
)


def _draft(obj, modality: Modality) -> ConstraintDraft:
    return ConstraintDraft(
        source_span="x",
        effect="deny",
        principal_mentions=["Agent A"],
        modality=modality,
        object=obj,
    )


def test_exact_selector_with_access_is_access() -> None:
    result = route(_draft(EmailSelectorObject(), Modality.ACCESS))
    assert result.kind == "access"


def test_exact_selector_with_knowledge_is_unsupported() -> None:
    result = route(_draft(EmailSelectorObject(), Modality.KNOWLEDGE))
    assert result.kind == "unsupported"
    assert result.reason == "selector_with_knowledge_modality"


def test_proposition_is_confidentiality_even_with_access_verb() -> None:
    result = route(_draft(PropositionObject(text="I have cancer"), Modality.ACCESS))
    assert result.kind == "confidentiality"


def test_topic_is_confidentiality() -> None:
    result = route(
        _draft(TopicObject(text="my financial information"), Modality.KNOWLEDGE)
    )
    assert result.kind == "confidentiality"


def test_content_class_is_not_supported() -> None:
    result = route(
        _draft(ContentClassObject(text="flight reservations"), Modality.ACCESS)
    )
    assert result.kind == "unsupported"
