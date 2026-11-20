from __future__ import annotations

from rosalind.policy.application.preview import MARKER, render_preview
from rosalind.policy.domain.drafts import (
    ImpactReport,
    ResolvedConstraint,
    ResolvedParticipant,
)


def _access() -> ResolvedConstraint:
    return ResolvedConstraint(
        kind="access",
        effect="deny",
        participants=[
            ResolvedParticipant(
                mention="John Smith",
                roles=["from"],
                person_id="person_123",
                addresses=["john@example.com"],
                matched_by="exact_name",
            )
        ],
    )


def test_access_preview_states_all_agents_and_not_enforced() -> None:
    preview = render_preview(_access(), ImpactReport(matching_emails=312))

    assert "Applies to all agents" in preview
    assert "sent by john@example.com" in preview
    assert "312 emails" in preview
    assert "Enforcement is not active yet" in preview


def test_access_preview_mentions_quoted_copy_limitation() -> None:
    preview = render_preview(_access(), ImpactReport())

    assert "quoted inside other emails" in preview


def test_confidentiality_preview_uses_marker() -> None:
    resolved = ResolvedConstraint(
        kind="confidentiality",
        effect="deny",
        statement="The user has cancer",
        statement_kind="fact",
    )

    preview = render_preview(resolved, ImpactReport())

    assert "The user has cancer" in preview
    assert MARKER in preview
    assert "AI-based and best-effort" in preview
    assert "Enforcement is not active yet" in preview
