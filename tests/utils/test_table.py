"""Tests for aula.utils.table."""

import builtins
import os
from datetime import date, datetime, time

import pytest

from aula.models.calendar_event import CalendarEvent
from aula.utils.table import (
    CARD_MAX_WIDTH,
    CARD_MIN_WIDTH,
    CalendarTableData,
    _fit_widths,
    _natural_widths,
    _print_card_with_rich,
    _print_plain,
    _print_rows_with_rich,
    _print_with_rich,
    build_calendar_table,
    card_width,
    print_calendar_table,
    print_row_table,
    print_text_card,
    print_wrapped_row_table,
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


class TestCardWidth:
    def test_follows_terminal_width(self, monkeypatch):
        monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: os.terminal_size((72, 24)))
        assert card_width() == 71

    def test_clamped_to_max(self, monkeypatch):
        monkeypatch.setattr(
            "shutil.get_terminal_size", lambda fallback: os.terminal_size((400, 24))
        )
        assert card_width() == CARD_MAX_WIDTH

    def test_clamped_to_min(self, monkeypatch):
        monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: os.terminal_size((10, 24)))
        assert card_width() == CARD_MIN_WIDTH


class TestPrintTextCard:
    HEADERS = ["Barn Et · 3.1 · Week 34", "Skole"]
    BLOCKS = ["DANSK:", "En kort tekst.", "- Et punkt", "- Et andet punkt"]

    def _plain_lines(self, capsys, monkeypatch, **kwargs):
        monkeypatch.setattr("aula.utils.table._print_card_with_rich", lambda *a: False)
        print_text_card(**kwargs)
        return capsys.readouterr().out.splitlines()

    def test_plain_box_is_rectangular(self, capsys, monkeypatch):
        lines = self._plain_lines(
            capsys, monkeypatch, header_lines=self.HEADERS, body_blocks=self.BLOCKS, width=40
        )

        assert all(len(line) == 40 for line in lines)
        assert lines[0].startswith("┌") and lines[0].endswith("┐")
        assert lines[-1].startswith("└") and lines[-1].endswith("┘")

    def test_header_is_divided_from_body(self, capsys, monkeypatch):
        lines = self._plain_lines(
            capsys, monkeypatch, header_lines=self.HEADERS, body_blocks=self.BLOCKS, width=40
        )
        divider = next(index for index, line in enumerate(lines) if line.startswith("├"))

        assert "Skole" in lines[divider - 1]
        assert "DANSK:" in lines[divider + 1]

    def test_blocks_are_separated_but_bullets_are_not(self, capsys, monkeypatch):
        lines = self._plain_lines(
            capsys, monkeypatch, header_lines=[], body_blocks=self.BLOCKS, width=40
        )
        body = [line.strip("│").strip() for line in lines[1:-1]]

        assert body == ["DANSK:", "", "En kort tekst.", "", "- Et punkt", "- Et andet punkt"]

    def test_long_text_wraps_with_bullet_indent(self, capsys, monkeypatch):
        lines = self._plain_lines(
            capsys,
            monkeypatch,
            header_lines=[],
            body_blocks=["- " + "ord " * 20],
            width=40,
        )
        body = [line.strip("│").rstrip() for line in lines[1:-1]]

        assert len(body) > 1
        assert body[0].strip().startswith("- ord")
        assert body[1].startswith("   ord")

    def test_empty_body_uses_placeholder(self, capsys, monkeypatch):
        lines = self._plain_lines(
            capsys,
            monkeypatch,
            header_lines=[],
            body_blocks=[],
            width=40,
            empty_body_text="(no weekly plan body)",
        )

        assert any("(no weekly plan body)" in line for line in lines)

    def test_renders_with_rich(self, capsys):
        pytest.importorskip("rich")

        print_text_card(header_lines=self.HEADERS, body_blocks=self.BLOCKS, width=60)
        out = capsys.readouterr().out

        assert "Barn Et" in out
        assert "Et andet punkt" in out

    def test_reports_missing_rich(self, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("rich"):
                raise ImportError("no rich")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        assert _print_card_with_rich(["Head"], ["Body"], 40) is False


class TestFitWidths:
    def test_keeps_natural_widths_when_they_fit(self):
        assert _fit_widths([10, 20], 40) == [10, 20]

    def test_shrinks_the_widest_column_first(self):
        assert _fit_widths([10, 30], 30) == [10, 17]

    def test_never_shrinks_below_the_floor(self):
        # 3 separator chars + two floors of 8 is already wider than 12.
        assert _fit_widths([20, 20], 12) == [8, 8]

    def test_narrow_column_keeps_its_natural_width(self):
        assert _fit_widths([3, 40], 20) == [3, 14]


class TestNaturalWidths:
    def test_uses_the_longest_line_of_a_cell(self):
        widths = _natural_widths(["Task"], [["short"], ["a longer line\nshort"]])
        assert widths == [len("a longer line")]

    def test_header_sets_the_floor(self):
        assert _natural_widths(["Weekday"], [["Mon"]]) == [len("Weekday")]


class TestPrintWrappedRowTable:
    HEADERS = ["Day", "Task"]
    ROWS = [["Tirsdag", "Bibliotek"], ["Onsdag", "Tur i skoven"]]

    def _plain_lines(self, capsys, monkeypatch, **kwargs):
        monkeypatch.setattr("aula.utils.table._print_rows_with_rich", lambda *a: False)
        print_wrapped_row_table(**kwargs)
        return capsys.readouterr().out.splitlines()

    def test_no_rows_prints_nothing(self, capsys):
        print_wrapped_row_table(self.HEADERS, [])
        assert capsys.readouterr().out == ""

    def test_renders_title_header_and_rows(self, capsys, monkeypatch):
        lines = self._plain_lines(
            capsys, monkeypatch, headers=self.HEADERS, rows=self.ROWS, title="Barn Et", width=40
        )

        assert lines[0] == "Barn Et"
        assert lines[1].startswith("Day     | Task")
        assert lines[2] == "--------+-------------"
        assert lines[3] == "Tirsdag | Bibliotek"

    def test_never_exceeds_the_given_width(self, capsys, monkeypatch):
        lines = self._plain_lines(
            capsys,
            monkeypatch,
            headers=["Day", "Task", "Class"],
            rows=[["Tirsdag", "En meget lang opgavetitel som ikke kan passe", "Historie 3.1"]],
            width=40,
        )

        assert lines and all(len(line) <= 40 for line in lines)

    def test_single_line_rows_stay_dense(self, capsys, monkeypatch):
        lines = self._plain_lines(
            capsys, monkeypatch, headers=self.HEADERS, rows=self.ROWS, width=40
        )

        assert "" not in lines

    def test_wrapped_rows_are_spaced_from_neighbours(self, capsys, monkeypatch):
        rows = [["Tirsdag", "Kort"], ["Onsdag", "Titel\n  Course: Et forløb"], ["Fredag", "Kort"]]
        lines = self._plain_lines(capsys, monkeypatch, headers=self.HEADERS, rows=rows, width=40)
        blanks = [index for index, line in enumerate(lines) if line == ""]

        assert len(blanks) == 2
        assert "Course: Et forløb" in lines[blanks[0] + 2]

    def test_renders_with_rich(self, capsys):
        pytest.importorskip("rich")

        print_wrapped_row_table(self.HEADERS, self.ROWS, title="Barn Et")
        out = capsys.readouterr().out

        assert "Tur i skoven" in out
        assert "Barn Et" in out
