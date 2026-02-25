from collections import defaultdict
from datetime import date, time
from typing import TypedDict

import click

try:
    from rich.console import Console  # type: ignore[import-not-found]
    from rich.table import Table  # type: ignore[import-not-found]

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

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


def print_calendar_table(table_data: CalendarTableData) -> None:
    """Prints the calendar table using rich if available, else plain text."""
    dates = table_data["dates"]
    slots = table_data["slots"]
    matrix = table_data["matrix"]

    date_headers = [d.strftime("%Y-%m-%d") for d in dates]
    slot_labels = [s.strftime("%H:%M") for s in slots]

    if _HAS_RICH:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Time")
        for date in date_headers:
            table.add_column(date)
        for slot_label, row in zip(slot_labels, matrix, strict=True):
            table.add_row(slot_label, *row)
        console = Console()
        console.print(table)
    else:
        col_width = max([len(h) for h in date_headers] + [10])

        def fmt_cell(cell):
            return cell.ljust(col_width)

        header = "Time     " + " ".join(fmt_cell(h) for h in date_headers)
        click.echo(header)
        click.echo("-" * len(header))
        for slot_label, row in zip(slot_labels, matrix, strict=True):
            click.echo(slot_label.ljust(8) + " " + " ".join(fmt_cell(cell) for cell in row))
