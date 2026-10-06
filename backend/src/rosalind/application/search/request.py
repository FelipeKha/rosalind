"""Online search: the request DTO and the shared search enums.

Phase 0 defines the application-layer request object that Prepare (phase 1)
consumes. It is plain and framework-free: no Pydantic, no SQLAlchemy, no
provider imports. The MCP adapter maps its Pydantic ``SearchEmailsInput`` onto
``SearchRequest`` via ``to_search_request``, so the application layer never
sees the wire representation.

The enums here are shared with the eventual ``SearchPlan`` (see
``docs/features/search_plan_schema.py``); ``Direction`` in particular mirrors
the ``search.chunk.direction`` check constraint, which exposes four values.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Direction(StrEnum):
    """Matches the ``search.chunk.direction`` check constraint.

    All four values are exposed to the agent; ``unknown`` covers mailing-list
    deliveries and Bcc copies to unregistered aliases.
    """

    RECEIVED = "received"
    SENT = "sent"
    SELF = "self"
    UNKNOWN = "unknown"


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


@dataclass(frozen=True, slots=True)
class SearchRequestFilters:
    """The raw, unresolved filters as the agent supplied them.

    Values are not normalized here (that is Prepare's job): ``sender`` /
    ``recipient`` / ``participant`` may still hold ``"me"``, an entity id or an
    address. ``thread_of`` is a message id; Prepare resolves it to the message's
    current thread. An empty ``frozenset`` means "no constraint".
    """

    sender: frozenset[str] = field(default_factory=frozenset)
    recipient: frozenset[str] = field(default_factory=frozenset)
    participant: frozenset[str] = field(default_factory=frozenset)
    direction: Direction | None = None
    date_from: date | None = None
    date_before: date | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    exclude_tags: frozenset[str] = field(default_factory=frozenset)
    has_attachment: bool | None = None
    thread_of: uuid.UUID | None = None
    language: frozenset[str] = field(default_factory=frozenset)
    source_accounts: frozenset[uuid.UUID] = field(default_factory=frozenset)
    include_trash_spam: bool = False


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Everything Prepare needs to plan one search, before any resolution.

    ``sort`` is ``None`` until Prepare picks a default ("relevance" when there
    is a query, otherwise "date_desc").
    """

    query: str | None
    keywords: str | None
    filters: SearchRequestFilters
    sort: SortOrder | None
    group_by: GroupBy
    view: ResultView
    limit: int
    cursor: str | None
    mode: SearchMode


__all__ = [
    "Direction",
    "GroupBy",
    "ResultView",
    "SearchMode",
    "SearchRequest",
    "SearchRequestFilters",
    "SortOrder",
]
