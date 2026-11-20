"""Policy interpreter orchestration.

The local LLM proposes raw mentions; this module routes, resolves, validates,
previews and persists with deterministic code. Nothing is persisted before the
owner confirms a constraint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from rosalind.config import PolicySettings
from rosalind.policy.application.dates import resolve_date_mention
from rosalind.policy.application.ports import (
    Clock,
    NewPolicy,
    ParserFactory,
    PersonCandidate,
    PolicyRepository,
    PromptParser,
    SecretBox,
    SourceAccountRef,
)
from rosalind.policy.application.preview import policy_title, render_preview
from rosalind.policy.application.router import route
from rosalind.policy.application.versioning import interpreter_version
from rosalind.policy.domain.drafts import (
    ClarificationOption,
    ClarificationRequest,
    ConstraintState,
    ConstraintStateName,
    DraftPayload,
    DraftState,
    ImpactReport,
    PolicyDetail,
    PolicySource,
    PolicySummary,
    ResolvedConstraint,
    ResolvedParticipant,
)
from rosalind.policy.domain.errors import (
    ConstraintNotReadyError,
    DraftNotFoundError,
    ModelNotAllowedError,
    PolicyNotFoundError,
    UnsupportedConstraintError,
)
from rosalind.policy.domain.extraction import (
    ConstraintDraft,
    EmailSelectorObject,
    PropositionObject,
    RoleMention,
    TopicObject,
)
from rosalind.policy.domain.spec import (
    AccessPolicySpec,
    ConfidentialityPolicySpec,
    DateRangePredicate,
    DirectionPredicate,
    Effect,
    EmailResource,
    HasParticipantPredicate,
    InAccountPredicate,
    PolicyStatus,
    Principal,
    PrincipalType,
    ProtectedInformationResource,
    Role,
    Selector,
    Treatment,
)

_SELF_MENTIONS = {"i", "me", "my", "myself", "mine"}
_MAX_ROUNDS = 2


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().date()


class _Clarification(Exception):
    def __init__(self, request: ClarificationRequest) -> None:
        super().__init__(request.text)
        self.request = request


class _Unsupported(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InterpreterService:
    def __init__(
        self,
        repository: PolicyRepository,
        parser_factory: ParserFactory,
        secret_box: SecretBox,
        settings: PolicySettings,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._parser_factory = parser_factory
        self._secret_box = secret_box
        self._settings = settings
        self._clock = clock or SystemClock()

    # ------------------------------------------------------------------ drafts
    def create_draft(
        self, account_id: uuid.UUID, prompt: str, model_name: str | None
    ) -> DraftState:
        model = self._settings.resolve_model(model_name)
        if model is None:
            raise ModelNotAllowedError(f"model {model_name!r} is not in the allowlist")
        parser = self._parser_factory(model)
        extraction = parser.extract(prompt)
        version = interpreter_version(model)
        self._repository.delete_expired_drafts(self._clock.now())

        constraints = [
            self._process_constraint(
                account_id=account_id,
                parser=parser,
                prompt=prompt,
                index=index,
                draft=draft,
                overrides={},
                round_number=1,
            )
            for index, draft in enumerate(extraction.constraints)
        ]

        payload = DraftPayload(
            prompt=prompt,
            model=model.name,
            model_id=model.model,
            interpreter_version=version,
            constraints=constraints,
        )
        expires_at = self._clock.now() + timedelta(
            seconds=self._settings.draft_ttl_seconds
        )
        record = self._repository.create_draft(
            account_id,
            self._secret_box.encrypt(payload.model_dump_json()),
            expires_at,
        )
        self._repository.commit()
        return payload.to_state(record.draft_id, record.expires_at)

    def answer(
        self,
        account_id: uuid.UUID,
        draft_id: uuid.UUID,
        constraint_index: int,
        option_id: str,
    ) -> DraftState:
        payload = self._load_payload(account_id, draft_id)
        constraint = _constraint(payload, constraint_index)
        clarification = constraint.clarification
        if clarification is None:
            return payload.to_state(draft_id, self._expiry(account_id, draft_id))

        option = next((o for o in clarification.options if o.id == option_id), None)
        if option is None:
            raise UnsupportedConstraintError(f"option {option_id!r} is not offered")

        if option_id == "none":
            constraint.state = ConstraintStateName.UNSUPPORTED
            constraint.error = "user_declined"
            constraint.clarification = None
        else:
            constraint.overrides[clarification.field] = option_id
            constraint.clarification = None
            parser = self._parser_for(payload.model)
            if constraint.draft is None:
                raise ConstraintNotReadyError("constraint has no draft")
            updated = self._process_constraint(
                account_id=account_id,
                parser=parser,
                prompt=payload.prompt,
                index=constraint_index,
                draft=constraint.draft,
                overrides=constraint.overrides,
                round_number=clarification.round + 1,
            )
            payload.constraints[constraint_index] = updated

        self._save_payload(account_id, draft_id, payload)
        return payload.to_state(draft_id, self._expiry(account_id, draft_id))

    def confirm(
        self,
        account_id: uuid.UUID,
        draft_id: uuid.UUID,
        constraint_indexes: list[int] | None,
    ) -> list[PolicySummary]:
        payload = self._load_payload(account_id, draft_id)
        selected = (
            list(range(len(payload.constraints)))
            if constraint_indexes is None
            else constraint_indexes
        )

        summaries: list[PolicySummary] = []
        for index in selected:
            constraint = _constraint(payload, index)
            if constraint.state is ConstraintStateName.CONFIRMED:
                if constraint.policy is not None:
                    summaries.append(constraint.policy)
                continue
            if constraint.state is not ConstraintStateName.READY:
                raise ConstraintNotReadyError(
                    f"constraint {index} is {constraint.state.value}, not ready"
                )
            if constraint.resolved is None or constraint.spec is None:
                raise ConstraintNotReadyError(f"constraint {index} has no spec")

            resolved = constraint.resolved
            source = PolicySource(
                prompt=payload.prompt,
                confirmed_description=constraint.preview or "",
                interpreter_version=payload.interpreter_version,
                model_id=payload.model_id,
                confirmed_at=self._clock.now(),
            )
            summary = self._repository.create_policy(
                _new_policy(
                    account_id=account_id,
                    resolved=resolved,
                    spec=constraint.spec,
                    source=source,
                )
            )
            constraint.policy = summary
            constraint.state = ConstraintStateName.CONFIRMED
            summaries.append(summary)

        self._save_payload(account_id, draft_id, payload)
        return summaries

    def delete_draft(self, account_id: uuid.UUID, draft_id: uuid.UUID) -> None:
        self._repository.delete_draft(account_id, draft_id)
        self._repository.commit()

    def purge_expired(self) -> int:
        deleted = self._repository.delete_expired_drafts(self._clock.now())
        self._repository.commit()
        return deleted

    # ---------------------------------------------------------------- policies
    def list_policies(self, account_id: uuid.UUID) -> list[PolicySummary]:
        return self._repository.list_policies(account_id)

    def get_policy(self, account_id: uuid.UUID, policy_id: uuid.UUID) -> PolicyDetail:
        detail = self._repository.get_policy(account_id, policy_id)
        if detail is None:
            raise PolicyNotFoundError(f"policy {policy_id} not found")
        return detail

    def set_policy_status(
        self, account_id: uuid.UUID, policy_id: uuid.UUID, status: str
    ) -> PolicySummary:
        summary = self._repository.set_policy_status(account_id, policy_id, status)
        if summary is None:
            raise PolicyNotFoundError(f"policy {policy_id} not found")
        self._repository.commit()
        return summary

    # -------------------------------------------------------------- processing
    def _process_constraint(
        self,
        *,
        account_id: uuid.UUID,
        parser: PromptParser,
        prompt: str,
        index: int,
        draft: ConstraintDraft,
        overrides: dict[str, str],
        round_number: int,
    ) -> ConstraintState:
        state = ConstraintState(
            index=index, state=ConstraintStateName.INVALID, draft=draft
        )
        state.unsupported_parts.extend(part.text for part in draft.unsupported_parts)

        if not _contains_span(prompt, draft.source_span):
            return _unsupported(state, "extraction_failed")

        routed = route(draft)
        if routed.kind == "unsupported":
            return _unsupported(state, routed.reason or "unsupported")

        try:
            spec: AccessPolicySpec | ConfidentialityPolicySpec
            if routed.kind == "access":
                resolved = self._resolve_access(
                    account_id, draft, overrides, round_number
                )
                spec = _access_spec(resolved)
            else:
                resolved = self._resolve_confidentiality(parser, draft)
                spec = _confidentiality_spec(resolved)
        except _Clarification as exc:
            state.state = ConstraintStateName.NEEDS_CLARIFICATION
            state.clarification = exc.request
            state.kind = routed.kind
            state.assumptions = _agent_scope_assumption(draft)
            return state
        except _Unsupported as exc:
            return _unsupported(state, exc.reason)
        except UnsupportedConstraintError as exc:
            return _unsupported(state, str(exc))

        impact = _impact(self._repository, account_id, resolved)
        state.kind = resolved.kind
        state.resolved = resolved
        state.spec = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
        state.impact = impact
        state.assumptions = resolved.assumptions
        state.resolution_notes = resolved.resolution_notes
        enforcement_live = (
            self._settings.access_enforcement_enabled
            if routed.kind == "access"
            else self._settings.enforcement_live
        )
        state.preview = render_preview(
            resolved,
            impact,
            enforcement_live=enforcement_live,
        )
        state.state = ConstraintStateName.READY
        return state

    def _resolve_access(
        self,
        account_id: uuid.UUID,
        draft: ConstraintDraft,
        overrides: dict[str, str],
        round_number: int,
    ) -> ResolvedConstraint:
        obj = draft.object
        if not isinstance(obj, EmailSelectorObject):
            raise _Unsupported("unsupported_selector")

        participants: list[ResolvedParticipant] = []
        notes: list[str] = []
        assumptions = _agent_scope_assumption(draft)

        for position, participant in enumerate(obj.participants):
            field = f"participant:{position}"
            candidate, matched_by = self._resolve_person(
                account_id,
                participant.mention,
                overrides.get(field),
                field,
                round_number,
            )
            roles = _roles(participant.role_mention)
            participants.append(
                ResolvedParticipant(
                    mention=participant.mention,
                    roles=roles,
                    person_id=str(candidate.person_id),
                    addresses=candidate.addresses,
                    matched_by=matched_by,
                )
            )
            notes.append(
                f"{participant.mention} matched {candidate.display_name} ({matched_by})"
            )

        account_id_value: str | None = None
        account_label: str | None = None
        if obj.account_mention:
            account = self._resolve_account(
                account_id,
                obj.account_mention,
                overrides.get("account"),
                round_number,
            )
            account_id_value = str(account.id)
            account_label = account.display_name or account.name
            notes.append(f"Account matched {account_label}")

        date_from: date | None = None
        date_to: date | None = None
        if obj.date_range is not None:
            date_range = resolve_date_mention(
                obj.date_range.mention, self._clock.today()
            )
            if date_range is None:
                raise _Unsupported("unsupported_date")
            date_from = date_range.from_
            date_to = date_range.to
            if date_from or date_to:
                frozen = _date_note(date_from, date_to)
                assumptions.append(f"Dates frozen at confirmation: {frozen}.")

        if (
            not participants
            and account_id_value is None
            and date_from is None
            and date_to is None
            and obj.direction is None
        ):
            raise _Unsupported("empty_selector")

        return ResolvedConstraint(
            kind="access",
            effect=draft.effect.value,
            participants=participants,
            account_id=account_id_value,
            account_label=account_label,
            date_from=date_from,
            date_to=date_to,
            direction=obj.direction,
            assumptions=assumptions,
            resolution_notes=notes,
        )

    def _resolve_confidentiality(
        self, parser: PromptParser, draft: ConstraintDraft
    ) -> ResolvedConstraint:
        if draft.effect.value != "deny":
            raise _Unsupported("confidentiality_permit_unsupported")

        obj = draft.object
        if isinstance(obj, PropositionObject):
            kind = "fact"
            text = obj.text
        elif isinstance(obj, TopicObject):
            kind = "topic"
            text = obj.text
        else:
            raise _Unsupported("unsupported_protected_information")

        canonical = parser.canonicalize(text, kind)
        if canonical.is_question_or_instruction:
            raise _Unsupported("question_or_instruction")
        if not canonical.atomic:
            raise _Unsupported("not_atomic")
        if not canonical.text.strip():
            raise _Unsupported("empty_statement")

        return ResolvedConstraint(
            kind="confidentiality",
            effect="deny",
            statement=canonical.text.strip(),
            statement_kind=kind,  # type: ignore[arg-type]
            assumptions=_agent_scope_assumption(draft),
        )

    def _resolve_person(
        self,
        account_id: uuid.UUID,
        mention: str,
        override: str | None,
        field: str,
        round_number: int,
    ) -> tuple[PersonCandidate, str]:
        if override:
            candidate = self._repository.get_person(uuid.UUID(override))
            if candidate is None:
                raise _Unsupported("unknown_person")
            return candidate, "user_choice"

        normalized = mention.strip().lower()
        if normalized in _SELF_MENTIONS:
            self_id = self._repository.self_person_id(account_id)
            if self_id is None:
                raise _Unsupported("self_person_not_set")
            candidate = self._repository.get_person(self_id)
            if candidate is None:
                raise _Unsupported("self_person_not_set")
            return candidate, "self"

        candidates = self._repository.find_people(mention)
        exact = [
            candidate
            for candidate in candidates
            if candidate.display_name.strip().lower() == normalized
            or normalized in candidate.addresses
        ]
        if len(exact) == 1:
            return exact[0], "exact_name"
        if len(candidates) >= 1:
            self._raise_clarification(
                field=field,
                round_number=round_number,
                question_code="choose_person",
                text=f"Which {mention.strip()}?",
                options=[
                    ClarificationOption(
                        id=str(candidate.person_id),
                        label=candidate.display_name,
                        detail=", ".join(candidate.addresses) or None,
                    )
                    for candidate in candidates
                ],
            )
        raise _Unsupported("unknown_person")

    def _resolve_account(
        self,
        account_id: uuid.UUID,
        mention: str,
        override: str | None,
        round_number: int,
    ) -> SourceAccountRef:
        if override:
            account = self._repository.get_source_account(
                account_id, uuid.UUID(override)
            )
            if account is None:
                raise _Unsupported("unknown_account")
            return account
        candidates = self._repository.find_source_accounts(account_id, mention)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            self._raise_clarification(
                field="account",
                round_number=round_number,
                question_code="choose_account",
                text=f"Which account is {mention.strip()!r}?",
                options=[
                    ClarificationOption(
                        id=str(candidate.id),
                        label=candidate.display_name or candidate.name,
                        detail=candidate.name,
                    )
                    for candidate in candidates
                ],
            )
        raise _Unsupported("unknown_account")

    def _raise_clarification(
        self,
        *,
        field: str,
        round_number: int,
        question_code: str,
        text: str,
        options: list[ClarificationOption],
    ) -> None:
        if round_number >= _MAX_ROUNDS:
            raise _Unsupported("max_rounds_reached")
        raise _Clarification(
            ClarificationRequest(
                question_code=question_code,
                text=text,
                options=[*options, ClarificationOption(id="none", label="Neither")],
                field=field,
                round=round_number,
                max_rounds=_MAX_ROUNDS,
            )
        )

    # ------------------------------------------------------------------ drafts
    def _load_payload(self, account_id: uuid.UUID, draft_id: uuid.UUID) -> DraftPayload:
        record = self._repository.get_draft(account_id, draft_id)
        if record is None:
            raise DraftNotFoundError(f"draft {draft_id} not found")
        return DraftPayload.model_validate_json(
            self._secret_box.decrypt(record.payload_encrypted)
        )

    def _save_payload(
        self, account_id: uuid.UUID, draft_id: uuid.UUID, payload: DraftPayload
    ) -> None:
        expires_at = self._clock.now() + timedelta(
            seconds=self._settings.draft_ttl_seconds
        )
        self._repository.update_draft(
            account_id,
            draft_id,
            self._secret_box.encrypt(payload.model_dump_json()),
            expires_at,
        )
        self._repository.commit()

    def _expiry(self, account_id: uuid.UUID, draft_id: uuid.UUID) -> datetime:
        record = self._repository.get_draft(account_id, draft_id)
        if record is None:
            raise DraftNotFoundError(f"draft {draft_id} not found")
        return record.expires_at

    def _parser_for(self, model_name: str) -> PromptParser:
        model = self._settings.model_for(model_name)
        if model is None:
            raise ModelNotAllowedError(f"model {model_name!r} is not in the allowlist")
        return self._parser_factory(model)


def _new_policy(
    *,
    account_id: uuid.UUID,
    resolved: ResolvedConstraint,
    spec: dict[str, object],
    source: PolicySource,
) -> NewPolicy:
    return NewPolicy(
        account_id=account_id,
        title=policy_title(resolved),
        policy_type=resolved.kind,
        principal_kind="all_agents",
        status=str(spec["status"]),
        spec=spec,
        source=source,
        statement=resolved.statement,
        statement_kind=resolved.statement_kind,
        interpreter_version=source.interpreter_version,
        model_id=source.model_id,
    )


def _access_spec(resolved: ResolvedConstraint) -> AccessPolicySpec:
    predicates: list[object] = []
    for participant in resolved.participants:
        predicates.append(
            HasParticipantPredicate(
                roles=[Role(role) for role in participant.roles],
                addresses=participant.addresses,
                person_id=participant.person_id,
            )
        )
    if resolved.account_id is not None:
        predicates.append(InAccountPredicate(source_account_id=resolved.account_id))
    if resolved.date_from is not None or resolved.date_to is not None:
        predicates.append(
            DateRangePredicate(from_date=resolved.date_from, to=resolved.date_to)
        )
    if resolved.direction is not None:
        predicates.append(DirectionPredicate(direction=resolved.direction))

    return AccessPolicySpec(
        effect=Effect(resolved.effect),
        principal=Principal(type=PrincipalType.ALL_AGENTS),
        resource=EmailResource(selector=Selector(predicates=predicates)),  # type: ignore[arg-type]
        status=PolicyStatus.ACTIVE,
    )


def _confidentiality_spec(
    resolved: ResolvedConstraint,
) -> ConfidentialityPolicySpec:
    if resolved.statement is None or resolved.statement_kind is None:
        raise UnsupportedConstraintError("confidentiality rule has no statement")
    return ConfidentialityPolicySpec(
        effect=Effect.DENY,
        principal=Principal(type=PrincipalType.ALL_AGENTS),
        resource=ProtectedInformationResource(
            kind=resolved.statement_kind,
            statement=resolved.statement,
        ),
        treatment=Treatment(),
        status=PolicyStatus.PENDING_ENFORCEMENT,
    )


def _impact(
    repository: PolicyRepository,
    account_id: uuid.UUID,
    resolved: ResolvedConstraint,
) -> ImpactReport:
    if resolved.kind == "confidentiality":
        return ImpactReport(note="available after the build")
    addresses = sorted(
        {
            address
            for participant in resolved.participants
            for address in participant.addresses
        }
    )
    if not addresses:
        return ImpactReport(
            matching_emails=None,
            matching_addresses=0,
            note="counts are available for participant selectors only",
        )
    return ImpactReport(
        matching_emails=repository.count_participant_emails(account_id, addresses),
        matching_addresses=len(addresses),
    )


def _constraint(payload: DraftPayload, index: int) -> ConstraintState:
    for constraint in payload.constraints:
        if constraint.index == index:
            return constraint
    raise DraftNotFoundError(f"constraint {index} not found")


def _unsupported(state: ConstraintState, reason: str) -> ConstraintState:
    state.state = ConstraintStateName.UNSUPPORTED
    state.error = reason
    state.clarification = None
    return state


def _contains_span(prompt: str, span: str) -> bool:
    def normalize(value: str) -> str:
        return " ".join(value.split()).lower()

    return bool(span.strip()) and normalize(span) in normalize(prompt)


def _roles(role: RoleMention) -> list[str]:
    if role is RoleMention.ANY:
        return [Role.FROM.value, Role.TO.value, Role.CC.value, Role.BCC.value]
    return [role.value]


def _agent_scope_assumption(draft: ConstraintDraft) -> list[str]:
    if draft.principal_mentions:
        return [
            (
                "This rule applies to all agents; agent-specific scoping is not "
                "supported yet."
            )
        ]
    return ["This rule applies to all agents."]


def _date_note(date_from: date | None, date_to: date | None) -> str:
    if date_from and date_to:
        return f"{date_from.isoformat()} to {date_to.isoformat()}"
    if date_from:
        return f"from {date_from.isoformat()}"
    if date_to:
        return f"before {date_to.isoformat()}"
    return "any date"
