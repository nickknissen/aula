"""Tests for aula.utils.dates."""

import datetime

from aula.utils.dates import parse_api_datetime


def test_parses_offset_timestamp():
    parsed = parse_api_datetime("2026-03-01T10:00:00+01:00")
    assert parsed == datetime.datetime(
        2026, 3, 1, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1))
    )


def test_parses_utc_z_suffix():
    """Aula writes UTC as a trailing Z."""
    parsed = parse_api_datetime("2026-03-01T09:00:00Z")
    assert parsed == datetime.datetime(2026, 3, 1, 9, 0, tzinfo=datetime.UTC)


def test_parses_naive_timestamp():
    parsed = parse_api_datetime("2026-03-01T09:00:00")
    assert parsed == datetime.datetime(2026, 3, 1, 9, 0)


def test_unreadable_value_is_none():
    assert parse_api_datetime("not-a-date") is None


def test_missing_value_is_none():
    assert parse_api_datetime(None) is None
    assert parse_api_datetime("") is None


def test_non_string_value_is_none():
    assert parse_api_datetime(12345) is None
