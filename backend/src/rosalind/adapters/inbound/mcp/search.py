"""MCP-facing input models for the email ``search`` tool.

These Pydantic models are the wire representation of a search request, and stay
confined to this adapter. ``to_search_request`` maps them onto the application
layer's plain ``SearchRequest`` dataclass, so no framework types leak into
``application`` or ``domain``.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from rosalind.adapters.inbound.mcp.schemas import (
    SearchCitation,
    SearchResult,
    SearchResultItem,
    SearchWarning,
)
from rosalind.application.search import (
    Direction,
    GroupBy,
    ResultView,
    SearchMode,
    SearchPlan,
    SearchRequest,
    SearchRequestFilters,
    SearchResponse,
    ShortCircuit,
    SortOrder,
)


class SearchFilters(BaseModel):
    """Lists are OR within a field; different fields are AND."""

    model_config = ConfigDict(extra="forbid")

    sender: Annotated[
        list[str] | None,
        Field(description="Email addresses or entity IDs (from find_entity)."),
    ] = None
    recipient: Annotated[list[str] | None, Field(description="To/Cc/Bcc.")] = None
    participant: Annotated[list[str] | None, Field(description="Any role.")] = None
    direction: Literal["received", "sent", "self", "unknown"] | None = None
    date_from: Annotated[date | None, Field(description="Inclusive. ISO date.")] = None
    date_before: Annotated[date | None, Field(description="Exclusive. ISO date.")] = (
        None
    )
    tags: Annotated[
        list[str] | None,
        Field(description="Any of. Namespaced, e.g. 'gmail:Projects'."),
    ] = None
    exclude_tags: list[str] | None = None
    has_attachment: bool | None = None
    thread_of: Annotated[
        uuid.UUID | None,
        Field(description="Message ID; the thread is resolved at query time."),
    ] = None
    language: Annotated[
        list[str] | None, Field(description="ISO 639-1, e.g. ['fr','en'].")
    ] = None
    source_accounts: list[uuid.UUID] | None = None
    include_trash_spam: bool = False


class SearchEmailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[
        str | None,
        Field(
            description="What you're looking for, in natural language. Used for semantic "
            "search, and for keyword search unless `keywords` is set."
        ),
    ] = None
    keywords: Annotated[
        str | None,
        Field(
            description="Optional exact-match terms for keyword search (names, IDs, "
            'amounts). Supports "quoted phrases".'
        ),
    ] = None
    filters: SearchFilters = SearchFilters()
    sort: Literal["relevance", "date_desc", "date_asc"] | None = None
    group_by: Literal["message", "thread"] = "message"
    view: Literal["metadata", "snippet"] = "snippet"
    limit: Annotated[int, Field(ge=1, le=25)] = 10
    cursor: str | None = None
    mode: Literal["hybrid", "lexical", "semantic"] = "hybrid"


def to_search_request(input: SearchEmailsInput) -> SearchRequest:
    """Map the MCP wire model onto the application-layer request dataclass."""
    filters = input.filters
    return SearchRequest(
        query=input.query,
        keywords=input.keywords,
        filters=SearchRequestFilters(
            sender=frozenset(filters.sender or ()),
            recipient=frozenset(filters.recipient or ()),
            participant=frozenset(filters.participant or ()),
            direction=Direction(filters.direction) if filters.direction else None,
            date_from=filters.date_from,
            date_before=filters.date_before,
            tags=frozenset(filters.tags or ()),
            exclude_tags=frozenset(filters.exclude_tags or ()),
            has_attachment=filters.has_attachment,
            thread_of=filters.thread_of,
            language=frozenset(filters.language or ()),
            source_accounts=frozenset(filters.source_accounts or ()),
            include_trash_spam=filters.include_trash_spam,
        ),
        sort=SortOrder(input.sort) if input.sort else None,
        group_by=GroupBy(input.group_by),
        view=ResultView(input.view),
        limit=input.limit,
        cursor=input.cursor,
        mode=SearchMode(input.mode),
    )


def to_search_result(plan: SearchPlan, response: SearchResponse) -> SearchResult:
    """Map an assembled search response onto the MCP ``search`` tool response."""
    return SearchResult(
        request_id=plan.context.request_id,
        audit_id=plan.context.audit_id,
        mode_requested=plan.mode_requested.value,
        mode_effective=plan.mode_effective.value,
        fingerprint=plan.fingerprint,
        applied_filters=response.applied_filters,
        warnings=[_to_warning(warning) for warning in response.warnings],
        results=[_to_item(record) for record in response.results],
        total_estimate=response.total_estimate,
        next_cursor=response.next_cursor,
    )


def to_short_circuit_result(result: ShortCircuit) -> SearchResult:
    """Map a Prepare short circuit onto the MCP ``search`` tool response."""
    return SearchResult(
        request_id=result.context.request_id,
        audit_id=result.context.audit_id,
        short_circuit=result.reason.value,
        explanation=result.explanation,
        applied_filters=result.applied(),
        warnings=[_to_warning(warning) for warning in result.warnings],
    )


def _to_item(record) -> SearchResultItem:
    return SearchResultItem(
        item_id=record.item_id,
        thread_id=record.thread_id,
        chunk_id=record.chunk_id,
        subject=record.subject,
        sender=record.sender,
        date=record.date,
        snippet=record.snippet,
        matched_in=record.matched_in,
        score=record.score,
        citation=SearchCitation(
            item_id=record.citation.item_id,
            chunk_id=record.citation.chunk_id,
            thread_id=record.citation.thread_id,
        ),
    )


def _to_warning(warning) -> SearchWarning:
    return SearchWarning(
        code=warning.code.value,
        message=warning.message,
        field_name=warning.field_name,
        suggestion=warning.suggestion,
    )
