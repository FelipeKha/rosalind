"""Deterministic date range resolution.

Relative expressions are resolved against the owner's today and frozen to
absolute dates. Unsupported expressions return ``None`` so the constraint is
reported as unsupported rather than guessed. Rolling windows are out of scope.

``to`` is exclusive, matching the search API's ``date_before``.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

_MONTHS = {
    name.lower(): index for index, name in enumerate(calendar.month_name) if name
}
_MONTHS.update(
    {name.lower(): index for index, name in enumerate(calendar.month_abbr) if name}
)

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_YEAR = re.compile(r"^([a-z]+)\s+(\d{4})$", re.IGNORECASE)
_YEAR = re.compile(r"^\d{4}$")
_LAST_N = re.compile(
    r"^(?:last|past|previous)\s+(\d+)\s+(day|week|month|year)s?$", re.IGNORECASE
)


@dataclass(frozen=True)
class DateRange:
    from_: date | None
    to: date | None


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _year_range(year: int) -> DateRange:
    return DateRange(date(year, 1, 1), date(year + 1, 1, 1))


def _month_range(year: int, month: int) -> DateRange:
    start = _month_start(year, month)
    return DateRange(start, _add_months(start, 1))


def _parse_iso(text: str) -> date | None:
    if not _ISO.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _strip_prefix(text: str, prefixes: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return None


def resolve_date_mention(mention: str, today: date) -> DateRange | None:
    """Resolve a single date mention to a frozen range, or ``None``."""
    text = " ".join(mention.strip().split())
    if not text:
        return None
    lowered = text.lower()

    if lowered in {"today"}:
        return DateRange(today, today + timedelta(days=1))
    if lowered in {"yesterday"}:
        return DateRange(today - timedelta(days=1), today)

    if lowered in {"last year", "previous year"}:
        return _year_range(today.year - 1)
    if lowered in {"this year", "current year"}:
        return _year_range(today.year)
    if lowered in {"last month", "previous month"}:
        return _month_range(*_previous_month(today))
    if lowered in {"this month", "current month"}:
        return _month_range(today.year, today.month)
    if lowered in {"last week", "previous week"}:
        start = today - timedelta(days=today.weekday() + 7)
        return DateRange(start, start + timedelta(days=7))

    match = _LAST_N.match(lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "day":
            return DateRange(today - timedelta(days=amount), today + timedelta(days=1))
        if unit == "week":
            return DateRange(today - timedelta(weeks=amount), today + timedelta(days=1))
        if unit == "month":
            return DateRange(_add_months(today, -amount), today + timedelta(days=1))
        if unit == "year":
            return DateRange(
                _add_months(today, -12 * amount), today + timedelta(days=1)
            )

    rest = _strip_prefix(text, ("before ", "until ", "up to "))
    if rest is not None:
        exact = _parse_iso(rest)
        if exact is not None:
            return DateRange(None, exact)
        month = _parse_month_year(rest, today.year)
        if month is not None:
            return DateRange(None, month)
        return None

    rest = _strip_prefix(text, ("after ", "since ", "from "))
    if rest is not None:
        exact = _parse_iso(rest)
        if exact is not None:
            return DateRange(exact, None)
        month = _parse_month_year(rest, today.year)
        if month is not None:
            return DateRange(month, None)
        year = _parse_year(rest)
        if year is not None:
            return DateRange(date(year, 1, 1), None)
        return None

    rest = _strip_prefix(text, ("in ",))
    if rest is not None:
        year = _parse_year(rest)
        if year is not None:
            return _year_range(year)
        month = _parse_month_year(rest, today.year)
        if month is not None:
            return DateRange(month, _add_months(month, 1))
        return None

    exact = _parse_iso(text)
    if exact is not None:
        return DateRange(exact, exact + timedelta(days=1))

    month = _parse_month_year(text, today.year)
    if month is not None:
        return DateRange(month, _add_months(month, 1))

    year = _parse_year(text)
    if year is not None:
        return _year_range(year)

    return None


def _previous_month(value: date) -> tuple[int, int]:
    if value.month == 1:
        return value.year - 1, 12
    return value.year, value.month - 1


def _parse_year(text: str) -> int | None:
    if not _YEAR.match(text):
        return None
    year = int(text)
    if 1900 <= year <= 2200:
        return year
    return None


def _parse_month_year(text: str, default_year: int) -> date | None:
    match = _MONTH_YEAR.match(text)
    if match:
        month = _MONTHS.get(match.group(1).lower())
        if month is None:
            return None
        return _month_start(int(match.group(2)), month)
    month = _MONTHS.get(text.lower())
    if month is not None:
        return _month_start(default_year, month)
    return None
