"""Unit tests for the MCP ``search`` input models."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from rosalind.adapters.inbound.mcp.search import SearchEmailsInput, SearchFilters


def test_filters_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SearchFilters.model_validate({"unknown_field": "nope"})


def test_input_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SearchEmailsInput.model_validate({"bogus": 1})


def test_direction_accepts_all_four_canonical_values() -> None:
    for value in ("received", "sent", "self", "unknown"):
        assert SearchFilters(direction=value).direction == value


def test_direction_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        SearchFilters.model_validate({"direction": "draft"})


def test_limit_enforces_bounds() -> None:
    assert SearchEmailsInput(limit=1).limit == 1
    assert SearchEmailsInput(limit=25).limit == 25
    for bad in (0, 26):
        with pytest.raises(ValidationError):
            SearchEmailsInput(limit=bad)


@pytest.mark.parametrize("field", ["mode", "sort", "group_by", "view"])
def test_literal_fields_reject_unknown_values(field: str) -> None:
    with pytest.raises(ValidationError):
        SearchEmailsInput.model_validate({field: "not-a-real-value"})


def test_defaults_match_spec() -> None:
    input_ = SearchEmailsInput()
    assert input_.query is None
    assert input_.keywords is None
    assert input_.filters == SearchFilters()
    assert input_.sort is None
    assert input_.group_by == "message"
    assert input_.view == "snippet"
    assert input_.limit == 10
    assert input_.cursor is None
    assert input_.mode == "hybrid"


def test_thread_of_is_a_uuid() -> None:
    thread_of = uuid.uuid4()
    assert SearchFilters(thread_of=thread_of).thread_of == thread_of
    with pytest.raises(ValidationError):
        SearchFilters.model_validate({"thread_of": "not-a-uuid"})
