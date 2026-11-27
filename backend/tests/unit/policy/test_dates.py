from __future__ import annotations

from datetime import date

from rosalind.policy.application.dates import resolve_date_mention

TODAY = date(2026, 11, 19)


def test_iso_date_is_one_day() -> None:
    result = resolve_date_mention("2025-01-01", TODAY)

    assert result is not None
    assert result.from_ == date(2025, 1, 1)
    assert result.to == date(2025, 1, 2)


def test_before_iso_date_is_exclusive() -> None:
    result = resolve_date_mention("before 2025-01-01", TODAY)

    assert result is not None
    assert result.from_ is None
    assert result.to == date(2025, 1, 1)


def test_last_year() -> None:
    result = resolve_date_mention("last year", TODAY)

    assert result is not None
    assert result.from_ == date(2025, 1, 1)
    assert result.to == date(2026, 1, 1)


def test_last_three_months() -> None:
    result = resolve_date_mention("last 3 months", TODAY)

    assert result is not None
    assert result.from_ == date(2026, 8, 19)
    assert result.to == date(2026, 11, 20)


def test_month_and_year() -> None:
    result = resolve_date_mention("March 2025", TODAY)

    assert result is not None
    assert result.from_ == date(2025, 3, 1)
    assert result.to == date(2025, 4, 1)


def test_unsupported_expression_returns_none() -> None:
    assert resolve_date_mention("whenever I feel like it", TODAY) is None
