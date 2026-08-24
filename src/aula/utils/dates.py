"""Helpers for reading dates and times out of API responses."""

import datetime
from typing import Any


def parse_api_datetime(value: Any) -> datetime.datetime | None:
    """Parse an ISO 8601 timestamp from Aula, or ``None`` when unreadable.

    Aula writes timestamps three ways in the same response: with an offset,
    with a trailing ``Z`` for UTC, and naive. A field it has no value for
    arrives as ``null``, an empty string, or not at all. All of those, and
    anything else unparseable, give ``None``.

    >>> parse_api_datetime("2026-03-01T09:00:00Z")
    datetime.datetime(2026, 3, 1, 9, 0, tzinfo=datetime.timezone.utc)
    >>> parse_api_datetime(None) is None
    True
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
