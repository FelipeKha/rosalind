"""Search plan: the output of the Prepare step (online search pipeline, step 1).

Suggested location: backend/src/rosalind/application/search/plan.py

Layer: ``application``. Plain frozen dataclasses with no Pydantic and no
framework imports (DESIGN.md section 4: Pydantic is for API boundaries only).
The MCP adapter maps its ``SearchEmailsInput`` onto Prepare, and maps
``SearchPlan`` / ``ShortCircuit`` back onto the tool response.

Conventions
-----------
* Everything is immutable and hashable: ``frozen=True``, ``slots=True``,
  ``frozenset`` for unordered collections, ``tuple`` for ordered ones.
* An empty ``frozenset`` on a filter means "no constraint". A constraint that
  resolved to nothing (an entity with no handles, say) never reaches a plan:
  Prepare returns a ``ShortCircuit`` instead.
* ``__post_init__`` checks *internal* invariants. A ``ValueError`` raised from
  here is a bug in Prepare. User mistakes are raised earlier, as
  ``InvalidSearchRequest``.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NewType
from uuid import UUID

MAX_LIMIT = 25
"""Hard cap on results returned per call (DESIGN.md section 10)."""

# --------------------------------------------------------------------------
# Identifiers and value types
# --------------------------------------------------------------------------

AccountId = NewType("AccountId", UUID)
SourceAccountId = NewType("SourceAccountId", UUID)
EntityId = NewType("EntityId", UUID)
ThreadId = NewType("ThreadId", UUID)
ItemId = NewType("ItemId", UUID)
RequestId = NewType("RequestId", UUID)
AuditId = NewType("AuditId", UUID)

Handle = NewType("Handle", str)
"""A normalized address (lowercased, same normalizer as canonicalization)."""
Tag = NewType("Tag", str)
"""A source-namespaced tag, e.g. ``gmail:Projects``."""
LanguageCode = NewType("LanguageCode", str)
"""ISO 639-1 code, as stored on chunks by stage 4."""


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class SearchStrategy(StrEnum):
    RANKED = "ranked"  # query text present: retrieve, fuse, rerank
    LIST = "list"  # filters only: date-ordered listing with keyset paging


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    LEXICAL = "lexical"
    SEMANTIC = "semantic"


class SortOrder(StrEnum):
    RELEVANCE = "relevance"
    DATE_DESC = "date_desc"
    DATE_ASC = "date_asc"


class GroupBy(StrEnum):
    MESSAGE = "message"
    THREAD = "thread"


class ResultView(StrEnum):
    METADATA = "metadata"
    SNIPPET = "snippet"


class Direction(StrEnum):
    RECEIVED = "received"
    SENT = "sent"


class WarningCode(StrEnum):
    UNKNOWN_TAG = "unknown_tag"
    UNSEEN_HANDLE = "unseen_handle"
    UNKNOWN_LANGUAGE = "unknown_language"
    MODE_DEGRADED = "mode_degraded"
    QUERY_TRUNCATED = "query_truncated"
    LIMIT_CLAMPED = "limit_clamped"


class ShortCircuitReason(StrEnum):
    EMPTY_SCOPE = "empty_scope"
    NO_MATCHING_HANDLES = "no_matching_handles"
    CONTRADICTORY_FILTERS = "contradictory_filters"
    OUTSIDE_DATA_COVERAGE = "outside_data_coverage"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class InvalidSearchRequest(Exception):
    """A malformed request. The adapter maps it to an MCP tool error."""

    def __init__(self, field_name: str | None, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.field_name = field_name
        self.message = message
        self.hint = hint


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# --------------------------------------------------------------------------
# Plan components
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Who is asking, and the audit record opened for this call."""

    request_id: RequestId
    audit_id: AuditId
    client_id: str


@dataclass(frozen=True, slots=True)
class Scope:
    """What the caller may see. Mandatory and not a filter.

    Built from the authenticated account, never from tool arguments. The agent's
    ``source_accounts`` filter can only narrow this set. Every retrieval function
    takes the whole plan, so the scope cannot be forgotten.
    """

    account_id: AccountId
    source_account_ids: frozenset[SourceAccountId]

    def __post_init__(self) -> None:
        if not self.source_account_ids:
            raise ValueError("Scope needs at least one source account; an empty scope is a ShortCircuit")


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    """How a person reference in the request was expanded."""

    requested: str  # what the agent wrote: "me", an entity UUID, or an address
    entity_id: EntityId | None
    handles: frozenset[Handle]


@dataclass(frozen=True, slots=True)
class ResolvedFilters:
    """Normalized filters. Lists were OR within a field; fields are AND."""

    senders: frozenset[Handle] = frozenset()
    recipients: frozenset[Handle] = frozenset()  # to/cc/bcc
    participants: frozenset[Handle] = frozenset()  # any role
    direction: Direction | None = None
    tags_any: frozenset[Tag] = frozenset()
    tags_exclude: frozenset[Tag] = frozenset()
    has_attachment: bool | None = None
    thread_id: ThreadId | None = None
    languages: frozenset[LanguageCode] = frozenset()
    sent_from: datetime | None = None  # inclusive, UTC
    sent_before: datetime | None = None  # exclusive, UTC
    timezone_used: str = "UTC"  # IANA name used to turn dates into UTC bounds
    include_trash_spam: bool = False

    def __post_init__(self) -> None:
        for bound in (self.sent_from, self.sent_before):
            if bound is not None and not _is_utc(bound):
                raise ValueError("date bounds must be timezone-aware UTC datetimes")
        if self.sent_from and self.sent_before and self.sent_from >= self.sent_before:
            raise ValueError("sent_from must be before sent_before")
        if self.tags_any & self.tags_exclude:
            raise ValueError("a tag cannot be both included and excluded")

    def to_echo(self) -> dict[str, object]:
        """JSON-friendly form for the response's ``applied_filters``."""
        return {
            "senders": sorted(self.senders),
            "recipients": sorted(self.recipients),
            "participants": sorted(self.participants),
            "direction": self.direction.value if self.direction else None,
            "tags": sorted(self.tags_any),
            "exclude_tags": sorted(self.tags_exclude),
            "has_attachment": self.has_attachment,
            "thread_id": str(self.thread_id) if self.thread_id else None,
            "language": sorted(self.languages),
            "date_from_utc": _iso(self.sent_from),
            "date_before_utc": _iso(self.sent_before),
            "timezone": self.timezone_used,
            "include_trash_spam": self.include_trash_spam,
        }


@dataclass(frozen=True, slots=True)
class LexicalQuery:
    """Structured keyword query. The outbound adapter renders it into engine
    syntax and does the escaping there, so engine details stay out of
    ``application``."""

    terms: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.terms and not self.phrases:
            raise ValueError("LexicalQuery needs at least one term or phrase")
        if any(not item.strip() for item in (*self.terms, *self.phrases)):
            raise ValueError("terms and phrases must be non-empty")


@dataclass(frozen=True, slots=True)
class QueryVector:
    """The embedded query. Never logged or echoed: only ``digest`` is."""

    values: tuple[float, ...] = field(repr=False)
    model: str
    model_version: str
    digest: str  # sha256 hex of the values, for logs and eval

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("QueryVector cannot be empty")

    @property
    def dimension(self) -> int:
        return len(self.values)


@dataclass(frozen=True, slots=True)
class PreparedQuery:
    semantic_text: str | None = None
    lexical: LexicalQuery | None = None
    vector: QueryVector | None = None


@dataclass(frozen=True, slots=True)
class Presentation:
    sort: SortOrder
    group_by: GroupBy
    view: ResultView
    limit: int

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")


@dataclass(frozen=True, slots=True)
class Budgets:
    """Candidate sizes per stage. Configuration, never agent input."""

    lexical_k: int  # per lexical branch
    semantic_k: int
    fused_k: int  # kept after fusion
    rerank_k: int  # sent to the reranker (ignored when reranking is off)
    window_k: int  # final ranked results available across pages

    def __post_init__(self) -> None:
        values = (self.lexical_k, self.semantic_k, self.fused_k, self.rerank_k, self.window_k)
        if any(value < 1 for value in values):
            raise ValueError("all budgets must be positive")
        if self.window_k > self.fused_k:
            raise ValueError("window_k cannot exceed fused_k")


@dataclass(frozen=True, slots=True)
class IndexVersions:
    """Everything a result depends on, so runs can be reproduced."""

    index_version: str
    embedding_model: str | None
    embedding_version: str | None
    reranker: str | None  # None means reranking is disabled


@dataclass(frozen=True, slots=True)
class ListPosition:
    """Keyset position for the ``list`` strategy."""

    occurred_at: datetime
    item_id: ItemId


@dataclass(frozen=True, slots=True)
class Cursor:
    """Decoded paging token. ``fingerprint`` ties it to one plan."""

    fingerprint: str
    window_offset: int | None = None  # ranked: position inside the candidate window
    list_position: ListPosition | None = None  # list: keyset

    def __post_init__(self) -> None:
        if (self.window_offset is None) == (self.list_position is None):
            raise ValueError("a cursor carries exactly one of window_offset / list_position")
        if self.window_offset is not None and self.window_offset < 0:
            raise ValueError("window_offset cannot be negative")


@dataclass(frozen=True, slots=True)
class PlanWarning:
    code: WarningCode
    message: str
    field_name: str | None = None
    suggestion: str | None = None


@dataclass(frozen=True, slots=True)
class PlanHints:
    """Optional facts that let later steps choose cheaper paths."""

    estimated_matching_chunks: int | None = None  # filter selectivity (hook, not used in v1)


@dataclass(frozen=True, slots=True)
class PrepareTimings:
    validate_ms: float
    resolve_ms: float
    embed_ms: float | None
    total_ms: float


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchPlan:
    """Everything steps 2 to 5 need. Nothing downstream re-reads the request."""

    context: RequestContext
    scope: Scope
    filters: ResolvedFilters
    resolved_entities: tuple[ResolvedEntity, ...]
    query: PreparedQuery
    strategy: SearchStrategy
    mode_requested: SearchMode
    mode_effective: SearchMode
    presentation: Presentation
    budgets: Budgets
    versions: IndexVersions
    cursor: Cursor | None = None
    warnings: tuple[PlanWarning, ...] = ()
    hints: PlanHints = PlanHints()
    timings: PrepareTimings | None = None

    def __post_init__(self) -> None:
        query = self.query

        if self.strategy is SearchStrategy.LIST:
            if query.lexical or query.vector or query.semantic_text:
                raise ValueError("the list strategy takes no query")
            if self.presentation.sort is SortOrder.RELEVANCE:
                raise ValueError("the list strategy cannot sort by relevance")
        else:
            needs_lexical = self.mode_effective in (SearchMode.HYBRID, SearchMode.LEXICAL)
            needs_vector = self.mode_effective in (SearchMode.HYBRID, SearchMode.SEMANTIC)
            if needs_lexical != (query.lexical is not None):
                raise ValueError(f"lexical query does not match mode {self.mode_effective}")
            if needs_vector != (query.vector is not None):
                raise ValueError(f"query vector does not match mode {self.mode_effective}")
            if query.vector is not None:
                if query.semantic_text is None:
                    raise ValueError("a query vector needs its semantic_text")
                if (query.vector.model, query.vector.model_version) != (
                    self.versions.embedding_model,
                    self.versions.embedding_version,
                ):
                    raise ValueError("query vector model does not match plan versions")

        # No silent corrections: a changed mode must be visible in the warnings.
        if self.mode_effective is not self.mode_requested and not any(
            warning.code is WarningCode.MODE_DEGRADED for warning in self.warnings
        ):
            raise ValueError("mode changed without a MODE_DEGRADED warning")

        if self.presentation.limit > self.budgets.window_k:
            raise ValueError("limit cannot exceed window_k")

        if self.cursor is not None:
            if self.strategy is SearchStrategy.RANKED:
                offset = self.cursor.window_offset
                if offset is None or offset >= self.budgets.window_k:
                    raise ValueError("ranked cursor must point inside the window")
            elif self.cursor.list_position is None:
                raise ValueError("list cursor needs a list_position")

    @property
    def fingerprint(self) -> str:
        """Stable hash of everything that changes *what* is retrieved.

        Excludes the cursor, page size, view, request context and timings, so a
        cursor stays valid across page-size changes but not across different
        queries, scopes, filters or index versions. The query vector is derived
        from ``semantic_text`` plus the model version, so only those are hashed.
        """
        f, q, v, b = self.filters, self.query, self.versions, self.budgets
        payload: dict[str, object] = {
            "account": str(self.scope.account_id),
            "sources": sorted(str(item) for item in self.scope.source_account_ids),
            "senders": sorted(f.senders),
            "recipients": sorted(f.recipients),
            "participants": sorted(f.participants),
            "direction": f.direction.value if f.direction else None,
            "tags_any": sorted(f.tags_any),
            "tags_exclude": sorted(f.tags_exclude),
            "has_attachment": f.has_attachment,
            "thread_id": str(f.thread_id) if f.thread_id else None,
            "languages": sorted(f.languages),
            "sent_from": _iso(f.sent_from),
            "sent_before": _iso(f.sent_before),
            "include_trash_spam": f.include_trash_spam,
            "semantic_text": q.semantic_text,
            "terms": list(q.lexical.terms) if q.lexical else None,
            "phrases": list(q.lexical.phrases) if q.lexical else None,
            "strategy": self.strategy.value,
            "mode": self.mode_effective.value,
            "sort": self.presentation.sort.value,
            "group_by": self.presentation.group_by.value,
            "budgets": [b.lexical_k, b.semantic_k, b.fused_k, b.rerank_k, b.window_k],
            "versions": [v.index_version, v.embedding_model, v.embedding_version, v.reranker],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def applied(self) -> dict[str, object]:
        """What the response echoes as ``applied_filters``."""
        return {
            **self.filters.to_echo(),
            "entities": _echo_entities(self.resolved_entities),
            "mode": self.mode_effective.value,
            "lexical": (
                {"terms": list(self.query.lexical.terms), "phrases": list(self.query.lexical.phrases)}
                if self.query.lexical
                else None
            ),
        }


# --------------------------------------------------------------------------
# Early exit and the Prepare result type
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShortCircuit:
    """Prepare found that nothing can match. Steps 2 to 5 are skipped, and the
    call is still audited."""

    context: RequestContext
    reason: ShortCircuitReason
    explanation: str
    filters: ResolvedFilters | None = None
    resolved_entities: tuple[ResolvedEntity, ...] = ()
    warnings: tuple[PlanWarning, ...] = ()

    def applied(self) -> dict[str, object]:
        base = self.filters.to_echo() if self.filters else {}
        return {**base, "entities": _echo_entities(self.resolved_entities)}


type PrepareResult = SearchPlan | ShortCircuit
"""Return type of ``prepare``. Malformed requests raise ``InvalidSearchRequest``."""


def _echo_entities(entities: tuple[ResolvedEntity, ...]) -> list[dict[str, object]]:
    return [
        {
            "requested": entity.requested,
            "entity_id": str(entity.entity_id) if entity.entity_id else None,
            "handles": sorted(entity.handles),
        }
        for entity in entities
    ]
