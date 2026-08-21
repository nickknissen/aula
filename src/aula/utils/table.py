import shutil
import textwrap
from collections import defaultdict
from collections.abc import Sequence
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


def _print_rows_with_rich(
    headers: Sequence[str], rows: Sequence[Sequence[str]], title: str | None
) -> bool:
    """Render a row table with ``rich``. Returns ``False`` if rich is not installed."""
    try:
        from rich.console import Console  # type: ignore[import-not-found]
        from rich.table import Table  # type: ignore[import-not-found]
    except ImportError:
        return False

    table = Table(title=title, show_header=True, header_style="bold magenta")
    for header in headers:
        table.add_column(header, overflow="fold")
    for row in rows:
        table.add_row(*row)
    Console().print(table)
    return True


def _print_rows_plain(
    headers: Sequence[str], rows: Sequence[Sequence[str]], title: str | None
) -> None:
    """Render a row table as fixed-width plain text."""
    widths = [
        max([len(str(header))] + [len(str(row[index])) for row in rows])
        for index, header in enumerate(headers)
    ]

    def render(cells: Sequence[str]) -> str:
        padded = [str(cell).ljust(width) for cell, width in zip(cells, widths, strict=True)]
        return " | ".join(padded).rstrip()

    if title:
        click.echo(title)
    header_line = render(headers)
    click.echo(header_line)
    click.echo("-" * len(header_line))
    for row in rows:
        click.echo(render(row))


def print_row_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    title: str | None = None,
) -> None:
    """Print a header + rows table using rich if available, else plain text.

    Every row must have exactly as many cells as ``headers``.
    """
    if not rows:
        return
    if not _print_rows_with_rich(headers, rows, title):
        _print_rows_plain(headers, rows, title)


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


CARD_MAX_WIDTH = 100
CARD_MIN_WIDTH = 40


def card_width(max_width: int = CARD_MAX_WIDTH) -> int:
    """Return the card width to use for the current terminal."""
    columns = shutil.get_terminal_size((80, 24)).columns
    return max(CARD_MIN_WIDTH, min(max_width, columns - 1))


BULLET_PREFIXES = ("-", "*", "•")


def _is_bullet(block: str) -> bool:
    return block.lstrip().startswith(BULLET_PREFIXES)


def _wrap_block(block: str, width: int) -> list[str]:
    """Wrap one text block to ``width``, hanging-indenting bullet lines."""
    lines = []
    for line in block.split("\n"):
        indent = "  " if _is_bullet(line) else ""
        lines.extend(textwrap.wrap(line, width=width, subsequent_indent=indent) or [""])
    return lines


def _print_card_with_rich(
    header_lines: Sequence[str], body_lines: Sequence[str], width: int
) -> bool:
    """Render a card with ``rich``. Returns ``False`` if rich is not installed."""
    try:
        from rich import box  # type: ignore[import-not-found]
        from rich.console import Console  # type: ignore[import-not-found]
        from rich.table import Table  # type: ignore[import-not-found]
        from rich.text import Text  # type: ignore[import-not-found]
    except ImportError:
        return False

    table = Table(box=box.ROUNDED, show_header=False, width=width)
    table.add_column(overflow="fold")
    if header_lines:
        table.add_row(Text("\n".join(header_lines), style="bold"))
        table.add_section()
    table.add_row(Text("\n".join(body_lines)))
    Console().print(table)
    return True


def _print_card_plain(header_lines: Sequence[str], body_lines: Sequence[str], width: int) -> None:
    """Render a card as a plain-text box."""
    inner = width - 4

    def row(text: str) -> str:
        return f"│ {text.ljust(inner)} │"

    click.echo("┌" + "─" * (width - 2) + "┐")
    if header_lines:
        for line in header_lines:
            click.echo(row(line))
        click.echo("├" + "─" * (width - 2) + "┤")
    for line in body_lines:
        click.echo(row(line))
    click.echo("└" + "─" * (width - 2) + "┘")


def print_text_card(
    header_lines: Sequence[str],
    body_blocks: Sequence[str],
    width: int | None = None,
    empty_body_text: str = "(no content)",
) -> None:
    """Print a bordered card: header lines, a divider, then wrapped body blocks.

    ``body_blocks`` are separated by a blank line, so paragraphs stay apart.
    Uses rich if available, else plain box-drawing characters.
    """
    box_width = width if width is not None else card_width()
    inner = box_width - 4

    body_lines: list[str] = []
    previous_block = ""
    for block in body_blocks:
        # Consecutive bullets belong to one list, so they stay on adjacent lines.
        if body_lines and not (_is_bullet(block) and _is_bullet(previous_block)):
            body_lines.append("")
        body_lines.extend(_wrap_block(block, inner))
        previous_block = block
    if not body_lines:
        body_lines = [empty_body_text]

    wrapped_headers = [
        line for header in header_lines for line in (_wrap_block(header, inner) or [""])
    ]

    if not _print_card_with_rich(wrapped_headers, body_lines, box_width):
        _print_card_plain(wrapped_headers, body_lines, box_width)


MIN_COLUMN_WIDTH = 8


def _natural_widths(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[int]:
    """Return the width each column needs to render unwrapped."""
    return [
        max(
            [len(header)] + [len(line) for row in rows for line in str(row[index]).split("\n")],
        )
        for index, header in enumerate(headers)
    ]


def _fit_widths(widths: list[int], available: int) -> list[int]:
    """Shrink the widest columns until the table fits ``available`` characters."""
    fitted = list(widths)
    floors = [min(width, MIN_COLUMN_WIDTH) for width in widths]
    separators = 3 * (len(fitted) - 1)
    while sum(fitted) + separators > available:
        shrinkable = [i for i, width in enumerate(fitted) if width > floors[i]]
        if not shrinkable:
            break
        widest = max(shrinkable, key=lambda i: fitted[i])
        fitted[widest] -= 1
    return fitted


def _print_rows_plain_wrapped(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    title: str | None,
    width: int,
) -> None:
    """Render a row table as plain text, wrapping cells to fit ``width``."""
    widths = _fit_widths(_natural_widths(headers, rows), width)

    def render(cells: Sequence[str]) -> str:
        return " | ".join(
            cell.ljust(cell_width) for cell, cell_width in zip(cells, widths, strict=True)
        ).rstrip()

    wrapped_rows = [
        [_wrap_block(str(cell), cell_width) for cell, cell_width in zip(row, widths, strict=True)]
        for row in rows
    ]
    heights = [max(len(cell) for cell in wrapped) for wrapped in wrapped_rows]

    if title:
        click.echo(title)
    click.echo(render(headers))
    click.echo("-+-".join("-" * cell_width for cell_width in widths))
    for index, wrapped in enumerate(wrapped_rows):
        # A row spanning several lines is hard to tell from its neighbours, so
        # give it breathing room while leaving runs of single-line rows dense.
        if index and max(heights[index - 1], heights[index]) > 1:
            click.echo()
        for line_index in range(heights[index]):
            click.echo(
                render([cell[line_index] if line_index < len(cell) else "" for cell in wrapped])
            )


def print_wrapped_row_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    title: str | None = None,
    width: int | None = None,
) -> None:
    """Print a header + rows table that wraps long cells instead of overflowing.

    Unlike :func:`print_row_table` this never renders a line wider than the
    terminal, which keeps tables with free-text columns readable.
    """
    if not rows:
        return
    if not _print_rows_with_rich(headers, rows, title):
        _print_rows_plain_wrapped(
            headers, rows, title, width if width is not None else card_width()
        )
