"""Snapshot test for the public MCP ``search`` tool schema.

The eval work must not change the agent-facing surface, so this pins the wire
field names and the key validation constraints of ``SearchEmailsInput`` and its
nested ``SearchFilters``.
"""

from __future__ import annotations

from rosalind.adapters.inbound.mcp.search import SearchEmailsInput, SearchFilters

_INPUT_FIELDS = {
    "query",
    "keywords",
    "filters",
    "sort",
    "group_by",
    "view",
    "limit",
    "cursor",
    "mode",
}

_FILTER_FIELDS = {
    "sender",
    "recipient",
    "participant",
    "direction",
    "date_from",
    "date_before",
    "tags",
    "exclude_tags",
    "has_attachment",
    "thread_of",
    "language",
    "source_accounts",
    "include_trash_spam",
}


def test_search_input_fields_are_stable() -> None:
    assert set(SearchEmailsInput.model_fields) == _INPUT_FIELDS
    assert SearchEmailsInput.model_config.get("extra") == "forbid"


def test_search_filter_fields_are_stable() -> None:
    assert set(SearchFilters.model_fields) == _FILTER_FIELDS
    assert SearchFilters.model_config.get("extra") == "forbid"


def test_limit_bounds_are_stable() -> None:
    schema = SearchEmailsInput.model_json_schema()
    limit = schema["properties"]["limit"]
    assert limit["minimum"] == 1
    assert limit["maximum"] == 25


def test_mode_is_hybrid_lexical_semantic() -> None:
    schema = SearchEmailsInput.model_json_schema()
    assert schema["properties"]["mode"]["default"] == "hybrid"
    assert set(schema["properties"]["mode"]["enum"]) == {
        "hybrid",
        "lexical",
        "semantic",
    }
