"""Unit tests for the ``SearchEmailsInput`` -> ``SearchRequest`` mapping."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from rosalind.adapters.inbound.mcp.search import (
    SearchEmailsInput,
    SearchFilters,
    to_search_request,
)
from rosalind.application.search import (
    Direction,
    GroupBy,
    ResultView,
    SearchMode,
    SearchRequestFilters,
    SortOrder,
)

CHUNK_DIRECTIONS = {"received", "sent", "self", "unknown"}


def test_direction_enum_matches_chunk_direction_constraint() -> None:
    assert {d.value for d in Direction} == CHUNK_DIRECTIONS


def test_map_defaults_to_empty() -> None:
    request = to_search_request(SearchEmailsInput())

    assert request.query is None
    assert request.keywords is None
    assert request.sort is None
    assert request.group_by is GroupBy.MESSAGE
    assert request.view is ResultView.SNIPPET
    assert request.limit == 10
    assert request.cursor is None
    assert request.mode is SearchMode.HYBRID

    filters = request.filters
    assert filters.sender == frozenset()
    assert filters.recipient == frozenset()
    assert filters.participant == frozenset()
    assert filters.direction is None
    assert filters.date_from is None
    assert filters.date_before is None
    assert filters.tags == frozenset()
    assert filters.exclude_tags == frozenset()
    assert filters.has_attachment is None
    assert filters.thread_of is None
    assert filters.language == frozenset()
    assert filters.source_accounts == frozenset()
    assert filters.include_trash_spam is False


def test_map_round_trips_every_field() -> None:
    thread_of = uuid.uuid4()
    source = uuid.uuid4()
    input_ = SearchEmailsInput(
        query="holidays in Spain",
        keywords='"invoice 2026-0412"',
        filters=SearchFilters(
            sender=["me", "alex.dupont@gmail.com"],
            recipient=["mike@turnerroofing.com"],
            participant=["billing@turnerroofing.com"],
            direction="received",
            date_from=date(2026, 1, 1),
            date_before=date(2026, 6, 1),
            tags=["gmail:Projects"],
            exclude_tags=["gmail:Newsletters"],
            has_attachment=True,
            thread_of=thread_of,
            language=["en", "fr"],
            source_accounts=[source],
            include_trash_spam=True,
        ),
        sort="date_desc",
        group_by="thread",
        view="metadata",
        limit=25,
        cursor="opaque-cursor",
        mode="semantic",
    )

    request = to_search_request(input_)

    assert request.query == "holidays in Spain"
    assert request.keywords == '"invoice 2026-0412"'
    assert request.sort is SortOrder.DATE_DESC
    assert request.group_by is GroupBy.THREAD
    assert request.view is ResultView.METADATA
    assert request.limit == 25
    assert request.cursor == "opaque-cursor"
    assert request.mode is SearchMode.SEMANTIC

    filters = request.filters
    assert filters.sender == frozenset({"me", "alex.dupont@gmail.com"})
    assert filters.recipient == frozenset({"mike@turnerroofing.com"})
    assert filters.participant == frozenset({"billing@turnerroofing.com"})
    assert filters.direction is Direction.RECEIVED
    assert filters.date_from == date(2026, 1, 1)
    assert filters.date_before == date(2026, 6, 1)
    assert filters.tags == frozenset({"gmail:Projects"})
    assert filters.exclude_tags == frozenset({"gmail:Newsletters"})
    assert filters.has_attachment is True
    assert filters.thread_of == thread_of
    assert filters.language == frozenset({"en", "fr"})
    assert filters.source_accounts == frozenset({source})
    assert filters.include_trash_spam is True


def test_search_request_is_immutable() -> None:
    request = to_search_request(SearchEmailsInput(query="hi"))

    with pytest.raises(FrozenInstanceError):
        request.query = "changed"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        request.filters.direction = Direction.SENT  # type: ignore[misc]


def test_search_request_filters_are_frozensets() -> None:
    request = to_search_request(
        SearchEmailsInput(filters=SearchFilters(tags=["gmail:Inbox"]))
    )

    assert isinstance(request.filters.tags, frozenset)
    with pytest.raises(AttributeError):
        request.filters.tags.add("gmail:Other")  # type: ignore[attr-defined]


def test_search_request_filters_defaults() -> None:
    filters = SearchRequestFilters()
    assert filters.sender == frozenset()
    assert filters.include_trash_spam is False
