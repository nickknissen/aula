from collections import defaultdict
from datetime import date, time
from typing import TypedDict

import click

from ..models import CalendarEvent


class CalendarTableData(TypedDict):
    dates: list[date]
    slots: list[time]
    matrix: list[list[str]]


def build_calendar_table(events: list[CalendarEvent]) -> CalendarTableData:
    """
    Build a calendar table structure: columns are dates, rows are event start times.
    Returns a dict with 'dates', 'slots', and 'matrix'.
    """
    date_set = set()
    slot_set = set()
    slot_events = defaultdict(lambda: defaultdict(list))

    for event in events:
        date = event.start_datetime.date()
        slot_time = event.start_datetime.time()
        date_set.add(date)
        slot_set.add(slot_time)
        slot_events[slot_time][date].append(event)

    dates = sorted(date_set)
    slots = sorted(slot_set)

    matrix = []
    for slot in slots:
        row = []
        for date in dates:
            evs = slot_events[slot].get(date, [])
            if evs:
                row.append(", ".join(e.title for e in evs))
            else:
                row.append("")
        matrix.append(row)

    return {"dates": dates, "slots": slots, "matrix": matrix}


def _print_with_rich(
    date_headers: list[str], slot_labels: list[str], matrix: list[list[str]]
) -> bool:
    """Render the table with ``rich``. Returns ``False`` if rich is not installed."""
    try:
        from rich.console import Console  # type: ignore[import-not-found]
        from rich.table import Table  # type: ignore[import-not-found]
    except ImportError:
        return False

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Time")
    for header in date_headers:
        table.add_column(header)
    for slot_label, row in zip(slot_labels, matrix, strict=True):
        table.add_row(slot_label, *row)
    Console().print(table)
    return True


def _print_plain(date_headers: list[str], slot_labels: list[str], matrix: list[list[str]]) -> None:
    """Render the table as fixed-width plain text."""
    col_width = max([len(h) for h in date_headers] + [10])

    def fmt_cell(cell: str) -> str:
        return cell.ljust(col_width)

    header = "Time     " + " ".join(fmt_cell(h) for h in date_headers)
    click.echo(header)
    click.echo("-" * len(header))
    for slot_label, row in zip(slot_labels, matrix, strict=True):
        click.echo(slot_label.ljust(8) + " " + " ".join(fmt_cell(cell) for cell in row))


def print_calendar_table(table_data: CalendarTableData) -> None:
    """Prints the calendar table using rich if available, else plain text."""
    date_headers = [d.strftime("%Y-%m-%d") for d in table_data["dates"]]
    slot_labels = [s.strftime("%H:%M") for s in table_data["slots"]]
    matrix = table_data["matrix"]

    if not _print_with_rich(date_headers, slot_labels, matrix):
        _print_plain(date_headers, slot_labels, matrix)
