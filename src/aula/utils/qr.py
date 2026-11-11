"""Show the MitID QR codes in a terminal during app login."""

import asyncio
import functools
import io
import sys

import click
import qrcode

_QR_FRAME_SECONDS = 1.0
_QR_FIRST_FRAME_SECONDS = 2.0
_DEFAULT_HEADER = (
    "Scan with your MitID app: open it, start the QR scanner, and hold the\n"
    "camera steady on the code below. The code comes in two halves that take\n"
    "turns in the same spot, so keep the phone still until the app has read\n"
    "both. It stays quiet until then, and asks you to approve the login once\n"
    "it has them."
)
_DEFAULT_PART_LABEL = "QR code {part} of 2:"
_DEFAULT_DONE_MESSAGE = "Codes read. Approve the login in your MitID app."


def _frame_seconds(index: int) -> float:
    """How long one half stays up; the first gets longer, before any movement."""
    return _QR_FIRST_FRAME_SECONDS if index == 0 else _QR_FRAME_SECONDS


@functools.cache
def _terminal_draws_blocks() -> bool:
    """Whether stdout can encode the block characters QR art is drawn with."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "█".encode(encoding)
    except UnicodeEncodeError, LookupError:
        return False
    return True


def _stdout_is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except ValueError:
        return False


def _render_qr(qr: qrcode.QRCode) -> str:
    """Render one QR code as a block of terminal text."""
    if _terminal_draws_blocks():
        out = io.StringIO()
        qr.print_ascii(out=out, invert=True)
        return out.getvalue().rstrip("\n")
    return "\n".join("".join("##" if cell else "  " for cell in row) for row in qr.get_matrix())


class TerminalQRDisplay:
    """Alternate the two QR halves in one spot, the way mitid.dk animates them.

    The MitID app has to read both halves, so they take turns in place instead
    of scrolling past each other. Pass ``show`` as ``on_qr_codes`` and ``done``
    as ``on_qr_done`` to ``authenticate()``, and call ``stop`` when it returns.

    ``header``, ``part_label`` (``{part}`` becomes 1 or 2) and ``done_message``
    replace the English text; ``None`` prints nothing in that place.
    """

    def __init__(
        self,
        *,
        header: str | None = _DEFAULT_HEADER,
        part_label: str | None = _DEFAULT_PART_LABEL,
        done_message: str | None = _DEFAULT_DONE_MESSAGE,
    ) -> None:
        self._header = header
        self._header_lines = [*header.splitlines(), ""] if header else []
        self._part_label = part_label
        self._done_message = done_message
        self._frames: list[str] = []
        self._generation = 0
        self._printed_generation = 0
        self._task: asyncio.Task[None] | None = None
        self._drawn_lines = 0

    def show(self, qr1: qrcode.QRCode, qr2: qrcode.QRCode) -> None:
        """Take a fresh pair of codes and keep them on screen."""
        frames = [_render_qr(qr1), _render_qr(qr2)]
        if frames != self._frames:
            self._frames = frames
            self._generation += 1

        if not _stdout_is_tty():
            self._print_once()
            return

        if self._task is None:
            self._task = asyncio.create_task(self._animate())

    def done(self) -> None:
        """The app has read the codes; retire them and say what happens next."""
        if self._task is None and not self._drawn_lines:
            return
        self.stop()
        if self._done_message:
            click.echo(self._done_message)

    def stop(self) -> None:
        """Take the codes off the screen, whatever ended the login."""
        if self._task is None:
            self._erase()
            return
        self._task.cancel()
        self._task = None
        self._erase()
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()

    def _label_lines(self, part: int) -> list[str]:
        return [self._part_label.format(part=part)] if self._part_label else []

    def _print_once(self) -> None:
        """Without a terminal to redraw, print each new pair a single time."""
        if self._printed_generation == self._generation:
            return
        self._printed_generation = self._generation
        if self._header:
            click.echo(self._header)
        for part, frame in enumerate(self._frames, 1):
            click.echo("\n".join(["", *self._label_lines(part), frame]))

    async def _animate(self) -> None:
        """Swap the halves in place until the login moves on."""
        index = 0
        sys.stdout.write("\x1b[?25l")
        while True:
            self._draw(index)
            await asyncio.sleep(_frame_seconds(index))
            index += 1

    def _draw(self, index: int) -> None:
        part = index % len(self._frames)
        lines = [
            *self._header_lines,
            *self._label_lines(part + 1),
            *self._frames[part].splitlines(),
        ]
        # Every frame occupies the same rows, so the codes never shift as they swap.
        tallest = max(len(frame.splitlines()) for frame in self._frames)
        height = tallest + len(self._header_lines) + len(self._label_lines(1))
        lines += [""] * (height - len(lines))

        if self._drawn_lines:
            sys.stdout.write(f"\x1b[{self._drawn_lines}A")
        for line in lines:
            sys.stdout.write(f"\x1b[2K{line}\n")
        sys.stdout.flush()
        self._drawn_lines = len(lines)

    def _erase(self) -> None:
        if not self._drawn_lines:
            return
        sys.stdout.write(f"\x1b[{self._drawn_lines}A")
        sys.stdout.write("\x1b[2K\n" * self._drawn_lines)
        sys.stdout.write(f"\x1b[{self._drawn_lines}A")
        sys.stdout.flush()
        self._drawn_lines = 0
