"""Tests for aula.models.calendar_event."""

import datetime

from aula.models.calendar_event import CalendarEvent, merge_duplicate_lessons


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


def _event(
    event_id: int,
    title: str = "DFA 2",
    teacher: str | None = None,
    *,
    start: tuple[int, int] = (8, 15),
    end: tuple[int, int] = (9, 0),
    location: str | None = "Room 101",
    belongs_to: int | None = 100,
    has_substitute: bool = False,
    substitute: str | None = None,
) -> CalendarEvent:
    """Build a lesson row, defaulting to the shape Aula duplicates per adult."""
    return CalendarEvent(
        id=event_id,
        title=title,
        start_datetime=datetime.datetime(2026, 9, 14, *start),
        end_datetime=datetime.datetime(2026, 9, 14, *end),
        teacher_name=teacher,
        has_substitute=has_substitute,
        substitute_name=substitute,
        location=location,
        belongs_to=belongs_to,
        teacher_names=[teacher] if teacher else [],
        substitute_names=[substitute] if substitute else [],
    )


def test_merge_collapses_one_row_per_teacher():
    """Aula's per-adult rows for one lesson become a single event."""
    merged = merge_duplicate_lessons(
        [
            _event(1, teacher="Lærer Nummer 1"),
            _event(2, teacher="Lærer Nummer 2"),
        ]
    )

    assert len(merged) == 1
    assert merged[0].teacher_names == ["Lærer Nummer 1", "Lærer Nummer 2"]
    # The scalar keeps pointing at the first adult for existing callers.
    assert merged[0].teacher_name == "Lærer Nummer 1"
    assert merged[0].id == 1


def test_merge_keeps_distinct_lessons_in_the_same_slot():
    """Two different subjects at the same time are not one lesson."""
    merged = merge_duplicate_lessons(
        [
            _event(1, title="DFA 2", teacher="A"),
            _event(2, title="Idræt", teacher="B"),
        ]
    )

    assert [e.title for e in merged] == ["DFA 2", "Idræt"]


def test_merge_keeps_lessons_in_different_rooms():
    """Same title and slot but a different room stays two events."""
    merged = merge_duplicate_lessons(
        [
            _event(1, teacher="A", location="Room 101"),
            _event(2, teacher="B", location="Room 102"),
        ]
    )

    assert len(merged) == 2


def test_merge_keeps_lessons_for_different_children():
    """A shared lesson is not collapsed across two children."""
    merged = merge_duplicate_lessons(
        [
            _event(1, teacher="A", belongs_to=100),
            _event(2, teacher="A", belongs_to=200),
        ]
    )

    assert [e.belongs_to for e in merged] == [100, 200]


def test_merge_keeps_separate_timeslots():
    """The same subject in two periods stays two events."""
    merged = merge_duplicate_lessons(
        [
            _event(1, teacher="A", start=(8, 15), end=(9, 0)),
            _event(2, teacher="A", start=(9, 30), end=(10, 15)),
        ]
    )

    assert len(merged) == 2


def test_merge_reports_a_substitute_from_any_row():
    """One row flagging a substitute makes the merged lesson a substitute one."""
    merged = merge_duplicate_lessons(
        [
            _event(1, teacher="A"),
            _event(2, teacher="B", has_substitute=True, substitute="Vikar"),
        ]
    )

    assert len(merged) == 1
    assert merged[0].has_substitute is True
    assert merged[0].substitute_names == ["Vikar"]
    assert merged[0].substitute_name == "Vikar"


def test_merge_deduplicates_repeated_teacher_names():
    """The same adult listed on both rows is named once."""
    merged = merge_duplicate_lessons([_event(1, teacher="A"), _event(2, teacher="A")])

    assert merged[0].teacher_names == ["A"]


def test_merge_leaves_inputs_untouched():
    """Merging returns new events rather than rewriting the ones passed in."""
    rows = [_event(1, teacher="A"), _event(2, teacher="B")]
    merge_duplicate_lessons(rows)

    assert rows[0].teacher_names == ["A"]
    assert rows[1].teacher_names == ["B"]


def test_merge_normalises_an_untouched_single_event():
    """A lone row keeps its own values and is returned as-is."""
    merged = merge_duplicate_lessons([_event(1, teacher="A")])

    assert len(merged) == 1
    assert merged[0].teacher_names == ["A"]
    assert merged[0].has_substitute is False


def test_merge_preserves_first_appearance_order():
    """Groups come back in the order their first row appeared."""
    merged = merge_duplicate_lessons(
        [
            _event(1, title="B-fag", teacher="X"),
            _event(2, title="A-fag", teacher="Y"),
            _event(3, title="B-fag", teacher="Z"),
        ]
    )

    assert [e.title for e in merged] == ["B-fag", "A-fag"]
    assert merged[0].teacher_names == ["X", "Z"]


def test_merged_event_serialises_teacher_lists():
    """``dict(event)`` carries the new lists for JSON consumers."""
    merged = merge_duplicate_lessons([_event(1, teacher="A"), _event(2, teacher="B")])

    result = dict(merged[0])
    assert result["teacher_names"] == ["A", "B"]
    assert result["substitute_names"] == []
    assert "_raw" not in result
