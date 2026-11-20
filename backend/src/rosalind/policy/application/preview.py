"""Template-rendered previews.

The LLM never writes text the user reads. Slots are filled from the resolved
constraint, the directory and the count service.
"""

from __future__ import annotations

from rosalind.policy.domain.drafts import ImpactReport, ResolvedConstraint

MARKER = "[REDACTED BY PRIVACY POLICY]"

_ROLE_LABELS = {
    "from": "sent by",
    "to": "addressed to",
    "cc": "cc'd to",
    "bcc": "bcc'd to",
}


def render_preview(
    resolved: ResolvedConstraint,
    impact: ImpactReport,
    *,
    enforcement_live: bool = False,
) -> str:
    if resolved.kind == "access":
        return _render_access(resolved, impact, enforcement_live)
    return _render_confidentiality(resolved, enforcement_live)


def policy_title(resolved: ResolvedConstraint) -> str:
    if resolved.kind == "confidentiality":
        verb = "Protect" if resolved.effect == "deny" else "Permit"
        return f"{verb}: {resolved.statement}"
    if resolved.effect == "deny":
        target = _participant_phrase(resolved)
        return f"Hide emails {target}" if target else "Hide matching emails"
    target = _participant_phrase(resolved)
    return f"Allow emails {target}" if target else "Allow matching emails"


def _render_access(
    resolved: ResolvedConstraint,
    impact: ImpactReport,
    enforcement_live: bool,
) -> str:
    lines: list[str] = ["Applies to all agents."]
    subject = "Agents"
    target = _participant_phrase(resolved)

    if resolved.effect == "deny":
        if target:
            lines.append(f"{subject} will not see emails {target}.")
        else:
            lines.append(f"{subject} will not see matching emails.")
    else:
        if target:
            lines.append(f"{subject} may see emails {target}.")
        else:
            lines.append(f"{subject} may see matching emails.")

    if resolved.account_label:
        lines.append(f"Restricted to the account {resolved.account_label}.")
    if resolved.date_from or resolved.date_to:
        lines.append(f"Date range: {_date_range(resolved)}.")
    if resolved.direction:
        lines.append(f"Direction: {resolved.direction}.")

    if resolved.effect == "deny" and target:
        lines.append(
            "Emails where the person is only cc'd are not affected unless the "
            "rule says so."
        )
        lines.append(
            "Text from these emails quoted inside other emails is not hidden yet."
        )

    if impact.matching_emails is not None:
        suffix = "email" if impact.matching_emails == 1 else "emails"
        lines.append(f"Currently matches {impact.matching_emails} {suffix}.")

    if enforcement_live:
        lines.append("Takes effect on the next request.")
    else:
        lines.append("Enforcement is not active yet. This rule is recorded only.")
    return " ".join(lines)


def _render_confidentiality(
    resolved: ResolvedConstraint,
    enforcement_live: bool,
) -> str:
    kind = "information" if resolved.statement_kind == "topic" else "statement"
    lines = [
        "Applies to all agents.",
        (
            "Agents will not receive anything that states or strongly implies "
            f'the following {kind}: "{resolved.statement}".'
        ),
        (
            f"Affected parts will be replaced by {MARKER}. The rest of each "
            "email stays visible."
        ),
        "Detection is AI-based and best-effort.",
    ]
    if enforcement_live:
        lines.append("Existing emails are processed first.")
    else:
        lines.append("Enforcement is not active yet. This rule is recorded only.")
    return " ".join(lines)


def _participant_phrase(resolved: ResolvedConstraint) -> str:
    parts: list[str] = []
    for participant in resolved.participants:
        roles = participant.roles or ["any"]
        label = _ROLE_LABELS.get(roles[0], "involving")
        addresses = ", ".join(participant.addresses)
        detail = addresses or participant.mention
        parts.append(f"{label} {detail}")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " and ".join(parts)


def _date_range(resolved: ResolvedConstraint) -> str:
    if resolved.date_from and resolved.date_to:
        return f"{resolved.date_from.isoformat()} to {resolved.date_to.isoformat()}"
    if resolved.date_from:
        return f"from {resolved.date_from.isoformat()}"
    if resolved.date_to:
        return f"before {resolved.date_to.isoformat()}"
    return "any date"
