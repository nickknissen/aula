"""Tests for aula.utils.table."""

from datetime import date, datetime, time

from aula.models.calendar_event import CalendarEvent
from aula.utils.table import build_calendar_table


def _make_event(*, title: str, start: datetime, end: datetime) -> CalendarEvent:
    return CalendarEvent(
        id=1,
        title=title,
        start_datetime=start,
        end_datetime=end,
        teacher_name=None,
        has_substitute=False,
        substitute_name=None,
        location=None,
        belongs_to=None,
    )


class TestBuildCalendarTable:
    def test_single_event(self):
        """One event produces 1 date column and 1 time row."""
        event = _make_event(
            title="Math",
            start=datetime(2026, 3, 2, 8, 0),
            end=datetime(2026, 3, 2, 9, 0),
        )
        table = build_calendar_table([event])

        assert table["dates"] == [date(2026, 3, 2)]
        assert table["slots"] == [time(8, 0)]
        assert table["matrix"] == [["Math"]]

    def test_multiple_days(self):
        """Events across different days produce sorted date columns."""
        e1 = _make_event(
            title="Math",
            start=datetime(2026, 3, 3, 8, 0),
            end=datetime(2026, 3, 3, 9, 0),
        )
        e2 = _make_event(
            title="Danish",
            start=datetime(2026, 3, 2, 10, 0),
            end=datetime(2026, 3, 2, 11, 0),
        )
        table = build_calendar_table([e1, e2])

        assert table["dates"] == [date(2026, 3, 2), date(2026, 3, 3)]
        assert table["slots"] == [time(8, 0), time(10, 0)]
        # Row 0 (08:00): empty on Mar 2, "Math" on Mar 3
        assert table["matrix"][0] == ["", "Math"]
        # Row 1 (10:00): "Danish" on Mar 2, empty on Mar 3
        assert table["matrix"][1] == ["Danish", ""]

    def test_same_time_different_days(self):
        """Same time slot across different days produces a single row."""
        e1 = _make_event(
            title="Math",
            start=datetime(2026, 3, 2, 8, 0),
            end=datetime(2026, 3, 2, 9, 0),
        )
        e2 = _make_event(
            title="English",
            start=datetime(2026, 3, 3, 8, 0),
            end=datetime(2026, 3, 3, 9, 0),
        )
        table = build_calendar_table([e1, e2])

        assert len(table["slots"]) == 1
        assert table["matrix"] == [["Math", "English"]]

    def test_empty_events(self):
        """No events produces empty structure."""
        table = build_calendar_table([])

        assert table["dates"] == []
        assert table["slots"] == []
        assert table["matrix"] == []
