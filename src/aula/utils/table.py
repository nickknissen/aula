from typing import List, Dict, Any
from collections import defaultdict

try:
    from rich.table import Table
    from rich.console import Console
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

from aula.models import CalendarEvent

def build_calendar_table(events: List[CalendarEvent]) -> Dict[str, Any]:
    """
    Build a calendar table structure: columns are dates, rows are event start times.
    Returns a dict with 'dates', 'slots', and 'matrix'.
    """
    # Gather all unique dates and event start times
    date_set = set()
    slot_set = set()
    slot_events = defaultdict(lambda: defaultdict(list))  # slot_events[slot][date] = [events]

    for event in events:
        date = event.start_datetime.date()
        slot_time = event.start_datetime.time()
        date_set.add(date)
        slot_set.add(slot_time)
        slot_events[slot_time][date].append(event)

    dates = sorted(date_set)
    slots = sorted(slot_set)

    # Build matrix
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

def print_calendar_table(table_data: Dict[str, Any]):
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
        for slot_label, row in zip(slot_labels, matrix):
            table.add_row(slot_label, *row)
        console = Console()
        console.print(table)
    else:
        # Fallback: plain text table
        col_width = max([len(h) for h in date_headers] + [10])
        def fmt_cell(cell):
            return cell.ljust(col_width)
        header = "Time     " + " ".join(fmt_cell(h) for h in date_headers)
        print(header)
        print("-" * len(header))
        for slot_label, row in zip(slot_labels, matrix):
            print(slot_label.ljust(8) + " " + " ".join(fmt_cell(cell) for cell in row))
