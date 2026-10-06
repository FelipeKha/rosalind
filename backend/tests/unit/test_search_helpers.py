"""Unit tests for the cursor codec and the query/dates/tags pure helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from rosalind.application.search import Cursor, ListPosition
from rosalind.application.search.cursor import HmacCursorCodec
from rosalind.application.search.dates import resolve_timezone, to_utc_bounds
from rosalind.application.search.ports import CursorDecodeError
from rosalind.application.search.query import normalize_semantic_text, parse_keywords
from rosalind.application.search.tags import canonicalize_language, canonicalize_tag

ACCOUNT = uuid.uuid4()
EMAIL_ID = uuid.uuid4()


def test_cursor_round_trips_window_offset() -> None:
    codec = HmacCursorCodec(b"secret")
    token = codec.encode(
        Cursor(fingerprint="abc", window_offset=3),
        account_id=ACCOUNT,
        index_version="v1",
    )
    decoded = codec.decode(token, account_id=ACCOUNT, index_version="v1")
    assert decoded.fingerprint == "abc"
    assert decoded.window_offset == 3
    assert decoded.list_position is None


def test_cursor_round_trips_list_position() -> None:
    codec = HmacCursorCodec(b"secret")
    position = ListPosition(
        occurred_at=datetime(2026, 3, 17, 13, 32, 8, tzinfo=UTC), email_id=EMAIL_ID
    )
    token = codec.encode(
        Cursor(fingerprint="abc", list_position=position),
        account_id=ACCOUNT,
        index_version="v1",
    )
    decoded = codec.decode(token, account_id=ACCOUNT, index_version="v1")
    assert decoded.list_position == position


def test_cursor_rejects_tampering() -> None:
    codec = HmacCursorCodec(b"secret")
    token = codec.encode(
        Cursor(fingerprint="abc", window_offset=0),
        account_id=ACCOUNT,
        index_version="v1",
    )
    payload, sig = token.split(".", 1)
    tampered = f"{payload}.{'A' * len(sig)}"
    with pytest.raises(CursorDecodeError):
        codec.decode(tampered, account_id=ACCOUNT, index_version="v1")


def test_cursor_rejects_wrong_account() -> None:
    codec = HmacCursorCodec(b"secret")
    token = codec.encode(
        Cursor(fingerprint="abc", window_offset=0),
        account_id=ACCOUNT,
        index_version="v1",
    )
    with pytest.raises(CursorDecodeError):
        codec.decode(token, account_id=uuid.uuid4(), index_version="v1")


def test_cursor_rejects_wrong_index_version() -> None:
    codec = HmacCursorCodec(b"secret")
    token = codec.encode(
        Cursor(fingerprint="abc", window_offset=0),
        account_id=ACCOUNT,
        index_version="v1",
    )
    with pytest.raises(CursorDecodeError):
        codec.decode(token, account_id=ACCOUNT, index_version="v2")


def test_query_normalization() -> None:
    assert normalize_semantic_text("  Roof\u00a0quote  ") == "Roof quote"


def test_parse_keywords_splits_terms_and_phrases() -> None:
    query = parse_keywords('"12 Elm St" roof "slate replacement"')
    assert query is not None
    assert query.terms == ("roof",)
    assert query.phrases == ("12 Elm St", "slate replacement")


def test_parse_keywords_empty() -> None:
    assert parse_keywords("   ") is None


def test_date_bounds_respect_timezone() -> None:
    sent_from, sent_before = to_utc_bounds(
        date(2026, 3, 1), date(2026, 4, 1), "Europe/Paris"
    )
    assert sent_from is not None and sent_before is not None
    assert sent_from.isoformat() == "2026-02-28T23:00:00+00:00"
    assert sent_before.isoformat() == "2026-03-31T22:00:00+00:00"


def test_date_bounds_missing_dates() -> None:
    sent_from, sent_before = to_utc_bounds(None, None, "UTC")
    assert sent_from is None and sent_before is None


def test_resolve_timezone_falls_back() -> None:
    assert resolve_timezone(None, "UTC") == "UTC"
    assert resolve_timezone("Bogus/Zone", "UTC") == "UTC"
    assert resolve_timezone("Europe/Paris", "UTC") == "Europe/Paris"


def test_tag_canonicalization_matches_case_insensitively() -> None:
    resolved, suggestion = canonicalize_tag(
        "gmail:projects", frozenset({"gmail:Projects"})
    )
    assert resolved == "gmail:Projects"
    assert suggestion is None


def test_tag_canonicalization_suggests_close_match() -> None:
    resolved, suggestion = canonicalize_tag(
        "gmail:Project", frozenset({"gmail:Projects"})
    )
    assert resolved == "gmail:Project"
    assert suggestion == "gmail:Projects"


def test_tag_canonicalization_unknown_without_suggestion() -> None:
    resolved, suggestion = canonicalize_tag("zzz:Tag", frozenset({"gmail:Projects"}))
    assert resolved == "zzz:Tag"
    assert suggestion is None


def test_language_canonicalization_lowercases() -> None:
    assert canonicalize_language(" EN ") == "en"
