"""Date-bound normalization for the Prepare step.

``date_from``/``date_before`` arrive as naive ISO dates; Prepare turns them into
timezone-aware UTC bounds using an IANA timezone (the Keycloak ``zoneinfo``
claim, or the server default). ``date_from`` is inclusive and ``date_before`` is
exclusive; both are the start of their local day converted to UTC, so DST
transitions are handled by ``zoneinfo`` rather than manual offsets.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
    "resolve_timezone",
    "to_utc_bounds",
]


def resolve_timezone(requested: str | None, default: str) -> str:
    """Pick the IANA timezone to use, validating it and falling back to default."""
    if requested:
        try:
            ZoneInfo(requested)
            return requested
        except ZoneInfoNotFoundError:
            pass
    return default


def to_utc_bounds(
    date_from: date | None,
    date_before: date | None,
    timezone_name: str,
) -> tuple[datetime | None, datetime | None]:
    """Return ``(sent_from, sent_before)`` as timezone-aware UTC datetimes.

    ``sent_from`` is the start of ``date_from`` in ``timezone_name`` (inclusive);
    ``sent_before`` is the start of ``date_before`` (exclusive). A missing date
    yields ``None`` for that bound.
    """
    tz = ZoneInfo(timezone_name)
    return (
        _start_of_day_utc(date_from, tz) if date_from is not None else None,
        _start_of_day_utc(date_before, tz) if date_before is not None else None,
    )


def _start_of_day_utc(day: date, tz: ZoneInfo) -> datetime:
    local_midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
    return local_midnight.astimezone(UTC)
