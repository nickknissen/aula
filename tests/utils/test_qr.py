import asyncio

import pytest
import qrcode

import aula
from aula import cli
from aula.utils import qr as qr_module
from aula.utils.qr import TerminalQRDisplay, _render_qr, _terminal_draws_blocks


def _qr(data: str) -> qrcode.QRCode:
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make()
    return qr


class TestQrFrameSchedule:
    def test_lingers_on_the_first_half_before_the_swapping_starts(self):
        """The first code needs time to be scanned before it starts moving."""
        assert qr_module._frame_seconds(0) == 2.0
        assert qr_module._frame_seconds(1) == 1.0
        assert qr_module._frame_seconds(2) == 1.0


class TestQrDisplay:
    """The two codes are halves of one value, so both have to reach the app."""

    @pytest.fixture(autouse=True)
    def _fast_frames(self, monkeypatch):
        monkeypatch.setattr(qr_module, "_QR_FRAME_SECONDS", 0.01)
        monkeypatch.setattr(qr_module, "_QR_FIRST_FRAME_SECONDS", 0.02)
        _terminal_draws_blocks.cache_clear()

    @pytest.mark.asyncio
    async def test_alternates_both_halves_until_the_codes_are_read(self, monkeypatch, capsys):
        """MitID sends a pair once, but a half the app never sees blocks the login."""
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: True)
        display = TerminalQRDisplay()

        display.show(_qr("part-one"), _qr("part-two"))
        await asyncio.sleep(0.05)
        display.done()

        out = capsys.readouterr().out
        assert "QR code 1 of 2" in out
        assert "QR code 2 of 2" in out
        assert "Approve the login in your MitID app" in out

    @pytest.mark.asyncio
    async def test_redraws_over_itself_instead_of_scrolling(self, monkeypatch, capsys):
        """Codes that scroll away leave the user scanning a stale one."""
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: True)
        display = TerminalQRDisplay()

        display.show(_qr("part-one"), _qr("part-two"))
        await asyncio.sleep(0.03)
        display.done()

        assert "\x1b[" in capsys.readouterr().out

    @pytest.mark.asyncio
    @pytest.mark.parametrize("header", [qr_module._DEFAULT_HEADER, None])
    async def test_keeps_every_frame_the_same_height(self, monkeypatch, capsys, header):
        """A block that changes height as the halves swap leaves art behind on screen."""
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: True)
        display = TerminalQRDisplay(header=header)

        display.show(_qr("part-one"), _qr("part-two"))
        await asyncio.sleep(0.05)
        display.done()

        blocks = capsys.readouterr().out.split("QR code 1 of 2:")
        assert len(blocks) > 2
        assert len({block.count("\n") for block in blocks[1:-1]}) == 1

    def test_prints_each_pair_once_without_a_terminal(self, monkeypatch, capsys):
        """MitID repeats the codes every poll; a log file should not repeat them too."""
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: False)
        display = TerminalQRDisplay()

        display.show(_qr("part-one"), _qr("part-two"))
        display.show(_qr("part-one"), _qr("part-two"))

        assert capsys.readouterr().out.count("QR code 1 of 2") == 1

    def test_prints_a_new_pair_when_the_codes_rotate(self, monkeypatch, capsys):
        """MitID rotates the value, and only the current pair can be scanned."""
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: False)
        display = TerminalQRDisplay()

        display.show(_qr("part-one"), _qr("part-two"))
        display.show(_qr("part-one-v2"), _qr("part-two-v2"))

        assert capsys.readouterr().out.count("QR code 1 of 2") == 2

    @pytest.mark.parametrize("tty", [True, False])
    def test_stop_writes_nothing_when_no_codes_were_shown(self, monkeypatch, capsys, tty):
        """Every command stops the display, and JSON output must stay parseable."""
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: tty)
        display = TerminalQRDisplay()

        display.stop()

        assert capsys.readouterr().out == ""

    @pytest.mark.asyncio
    async def test_stop_shows_the_cursor_after_animating(self, monkeypatch, capsys):
        """The animation hides the cursor, so ending it has to bring it back."""
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: True)
        display = TerminalQRDisplay()

        display.show(_qr("part-one"), _qr("part-two"))
        await asyncio.sleep(0.03)
        display.stop()

        assert capsys.readouterr().out.endswith("\x1b[?25h")

    def test_falls_back_to_ascii_when_blocks_cannot_be_encoded(self, monkeypatch):
        """A console that cannot print blocks would otherwise show a broken code."""
        monkeypatch.setattr(qr_module, "_terminal_draws_blocks", lambda: False)

        rendered = _render_qr(_qr("part-one"))

        assert rendered.isascii()
        assert "#" in rendered


class TestQrDisplayText:
    """A program with its own prompts should not get ours mixed in."""

    @pytest.fixture(autouse=True)
    def _fast_frames(self, monkeypatch):
        monkeypatch.setattr(qr_module, "_QR_FRAME_SECONDS", 0.01)
        monkeypatch.setattr(qr_module, "_QR_FIRST_FRAME_SECONDS", 0.02)
        _terminal_draws_blocks.cache_clear()

    @pytest.mark.asyncio
    async def test_uses_the_callers_text(self, monkeypatch, capsys):
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: True)
        display = TerminalQRDisplay(
            header="Scan koden med MitID-appen.",
            part_label="QR-kode {part} af 2:",
            done_message="Godkend login i appen.",
        )

        display.show(_qr("part-one"), _qr("part-two"))
        await asyncio.sleep(0.05)
        display.done()

        out = capsys.readouterr().out
        assert "Scan koden med MitID-appen." in out
        assert "QR-kode 1 af 2:" in out
        assert "QR-kode 2 af 2:" in out
        assert "Godkend login i appen." in out
        assert "QR code" not in out
        assert "Scan with your MitID app" not in out
        assert "Codes read" not in out

    def test_prints_only_the_codes_when_every_text_is_none(self, monkeypatch, capsys):
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: False)
        first, second = _qr("part-one"), _qr("part-two")
        display = TerminalQRDisplay(header=None, part_label=None, done_message=None)

        display.show(first, second)

        assert capsys.readouterr().out == f"\n{_render_qr(first)}\n\n{_render_qr(second)}\n"

    @pytest.mark.asyncio
    async def test_done_says_nothing_without_a_done_message(self, monkeypatch, capsys):
        monkeypatch.setattr(qr_module, "_stdout_is_tty", lambda: True)
        display = TerminalQRDisplay(done_message=None)

        display.show(_qr("part-one"), _qr("part-two"))
        await asyncio.sleep(0.03)
        display.done()

        assert capsys.readouterr().out.endswith("\x1b[?25h")


def test_is_exported_from_the_package():
    assert aula.TerminalQRDisplay is TerminalQRDisplay


def test_the_old_private_cli_name_still_works():
    """Consumers imported aula.cli._TerminalQRDisplay before it was public."""
    assert cli._TerminalQRDisplay is TerminalQRDisplay
