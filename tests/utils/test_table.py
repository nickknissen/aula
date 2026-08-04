"""Tests for aula.utils.table."""

import builtins
from datetime import date, datetime, time

import pytest

from aula.models.calendar_event import CalendarEvent
from aula.utils.table import (
    CalendarTableData,
    _print_plain,
    _print_rows_with_rich,
    _print_with_rich,
    build_calendar_table,
    print_calendar_table,
    print_row_table,
)


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


@pytest.fixture
def sample_table() -> CalendarTableData:
    return {
        "dates": [date(2026, 3, 2), date(2026, 3, 3)],
        "slots": [time(8, 0)],
        "matrix": [["Math", "English"]],
    }


class TestPrintCalendarTable:
    def test_plain_renders_headers_and_rows(self, sample_table, capsys):
        """The plain renderer emits the date headers and each time row."""
        _print_plain(
            [d.strftime("%Y-%m-%d") for d in sample_table["dates"]],
            [s.strftime("%H:%M") for s in sample_table["slots"]],
            sample_table["matrix"],
        )
        out = capsys.readouterr().out

        assert "2026-03-02" in out
        assert "2026-03-03" in out
        assert "08:00" in out
        assert "Math" in out and "English" in out

    def test_rich_renders_when_available(self, sample_table, capsys):
        """With rich installed the rich renderer reports success and emits content."""
        pytest.importorskip("rich")

        assert (
            _print_with_rich(
                [d.strftime("%Y-%m-%d") for d in sample_table["dates"]],
                [s.strftime("%H:%M") for s in sample_table["slots"]],
                sample_table["matrix"],
            )
            is True
        )
        assert "Math" in capsys.readouterr().out

    def test_rich_reports_failure_when_missing(self, monkeypatch):
        """Without rich the renderer returns False instead of raising."""
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("rich"):
                raise ImportError("no rich")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        assert _print_with_rich(["2026-03-02"], ["08:00"], [["Math"]]) is False

    def test_falls_back_to_plain_without_rich(self, sample_table, monkeypatch, capsys):
        """print_calendar_table still renders when rich is unavailable."""
        monkeypatch.setattr("aula.utils.table._print_with_rich", lambda *a: False)

        print_calendar_table(sample_table)
        out = capsys.readouterr().out

        assert "2026-03-02" in out
        assert "Math" in out


class TestPrintRowTable:
    HEADERS = ["Child", "Guardian", "Class"]
    ROWS = [("Barn Et", "Værge Et (Far)", "3.1")]

    def test_renders_with_rich(self, capsys):
        pytest.importorskip("rich")

        print_row_table(self.HEADERS, self.ROWS, title="Contacts")
        out = capsys.readouterr().out

        assert "Contacts" in out
        assert "Guardian" in out
        assert "Barn Et" in out

    def test_rich_reports_failure_when_missing(self, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("rich"):
                raise ImportError("no rich")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        assert _print_rows_with_rich(self.HEADERS, self.ROWS, None) is False

    def test_falls_back_to_plain_without_rich(self, monkeypatch, capsys):
        monkeypatch.setattr("aula.utils.table._print_rows_with_rich", lambda *a: False)

        print_row_table(self.HEADERS, self.ROWS, title="Contacts")
        out = capsys.readouterr().out

        assert "Contacts" in out
        assert "Child" in out
        assert "Værge Et (Far)" in out

    def test_plain_columns_are_width_aligned(self, monkeypatch, capsys):
        monkeypatch.setattr("aula.utils.table._print_rows_with_rich", lambda *a: False)

        print_row_table(["A", "B"], [("short", "x"), ("much longer value", "y")])
        lines = [line for line in capsys.readouterr().out.splitlines() if "|" in line]

        # Every rendered row puts its separator at the same offset.
        offsets = {line.index("|") for line in lines}
        assert len(offsets) == 1

    def test_no_output_for_empty_rows(self, capsys):
        print_row_table(self.HEADERS, [], title="Contacts")
        assert capsys.readouterr().out == ""
