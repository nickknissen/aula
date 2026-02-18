"""Tests for aula.models.calendar_event."""

import datetime

from aula.models.calendar_event import CalendarEvent


def test_calendar_event_creation():
    event = CalendarEvent(
        id=1,
        title="Math class",
        start_datetime=datetime.datetime(2025, 1, 15, 8, 0),
        end_datetime=datetime.datetime(2025, 1, 15, 9, 0),
        teacher_name="Mr. Smith",
        has_substitute=False,
        substitute_name=None,
        location="Room 101",
        belongs_to=42,
    )
    assert event.id == 1
    assert event.title == "Math class"
    assert event.teacher_name == "Mr. Smith"
    assert event.has_substitute is False
    assert event.substitute_name is None
    assert event.location == "Room 101"
    assert event.belongs_to == 42


def test_calendar_event_with_substitute():
    event = CalendarEvent(
        id=2,
        title="English",
        start_datetime=datetime.datetime(2025, 1, 15, 10, 0),
        end_datetime=datetime.datetime(2025, 1, 15, 11, 0),
        teacher_name="Mrs. Jones",
        has_substitute=True,
        substitute_name="Ms. Brown",
        location=None,
        belongs_to=None,
    )
    assert event.has_substitute is True
    assert event.substitute_name == "Ms. Brown"


def test_calendar_event_dict_conversion():
    event = CalendarEvent(
        id=1,
        title="Test",
        start_datetime=datetime.datetime(2025, 1, 1, 8, 0),
        end_datetime=datetime.datetime(2025, 1, 1, 9, 0),
        teacher_name=None,
        has_substitute=False,
        substitute_name=None,
        location=None,
        belongs_to=None,
    )
    result = dict(event)
    assert result["title"] == "Test"
    assert result["id"] == 1
    assert "_raw" not in result


def test_calendar_event_raw_preserved():
    raw = {"id": 1, "extra": "data"}
    event = CalendarEvent(
        id=1,
        title="Test",
        start_datetime=datetime.datetime(2025, 1, 1, 8, 0),
        end_datetime=datetime.datetime(2025, 1, 1, 9, 0),
        teacher_name=None,
        has_substitute=False,
        substitute_name=None,
        location=None,
        belongs_to=None,
        _raw=raw,
    )
    assert event._raw is raw
    assert "_raw" not in dict(event)
