"""Tests for aula.cli helpers."""

import asyncio
import json
import platform
from unittest.mock import AsyncMock, MagicMock

import click
import pytest
import qrcode
from click.testing import CliRunner

from aula import __version__, cli
from aula.cli import (
    _WIDGET_ID_CACHE,
    CONTACTS_PAGE_SIZE,
    MAX_CONTACT_PAGES,
    _fetch_contact_pages,
    _first_available_widget,
    _has_widget,
    _mu_task_classes,
    _mu_task_rows,
    _password_provider,
    _print_otp_code,
    _render_qr,
    _require_any_widget,
    _require_widget,
    _terminal_draws_blocks,
    _token_digits_provider,
    _with_child,
    easyiq_homework,
    easyiq_ugeplan,
    logout,
    print_mu_task_tables,
    report_sick,
)
from aula.const import (
    MIN_UDDANNELSE_TASK_WIDGETS,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_EASYIQ_WEEKPLAN,
)
from aula.models import (
    Child,
    EasyIQHomework,
    PresenceConfiguration,
    PresenceState,
    Profile,
)
from aula.models.mu_task import MUTask, MUTaskClass, MUTaskCourse
from aula.widgets import EasyIQChildNotInPortal


def _pager(total: int):
    """Return a fetch_page callable serving ``total`` items in 20-item pages."""
    calls: list[int] = []

    async def fetch_page(page: int) -> list[dict]:
        calls.append(page)
        start = (page - 1) * CONTACTS_PAGE_SIZE
        return [{"id": i} for i in range(start, min(start + CONTACTS_PAGE_SIZE, total))]

    return fetch_page, calls


class TestWidgetAvailability:
    """Aula issues tokens for widgets an account does not have."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _WIDGET_ID_CACHE.clear()
        yield
        _WIDGET_ID_CACHE.clear()

    def _client(self, widget_ids, side_effect=None):
        from unittest.mock import AsyncMock

        client = MagicMock()
        widgets = [MagicMock(widget_id=wid) for wid in widget_ids]
        client.get_widgets = AsyncMock(return_value=widgets, side_effect=side_effect)
        return client

    @pytest.mark.asyncio
    async def test_present_widget(self):
        assert await _has_widget(self._client(["0019", "0030"]), "0019") is True

    @pytest.mark.asyncio
    async def test_absent_widget(self):
        assert await _has_widget(self._client(["0142", "0128"]), "0019") is False

    @pytest.mark.asyncio
    async def test_a_failed_lookup_does_not_block_the_command(self):
        """Incomplete information is no reason to refuse to try."""
        client = self._client([], side_effect=RuntimeError("boom"))

        assert await _has_widget(client, "0019") is True

    @pytest.mark.asyncio
    async def test_the_list_is_fetched_once_per_client(self):
        """weekly-summary asks about five providers in a row."""
        client = self._client(["0019"])

        for widget_id in ("0019", "0030", "0029", "0004", "0062"):
            await _has_widget(client, widget_id)

        assert client.get_widgets.await_count == 1

    @pytest.mark.asyncio
    async def test_a_failed_lookup_is_not_retried_per_provider(self):
        client = self._client([], side_effect=RuntimeError("boom"))

        for widget_id in ("0019", "0030", "0029"):
            await _has_widget(client, widget_id)

        assert client.get_widgets.await_count == 1

    @pytest.mark.asyncio
    async def test_require_widget_names_the_widget_and_points_at_aula_widgets(self, capsys):
        allowed = await _require_widget(self._client(["0142"]), "0019", "Biblioteket")

        assert allowed is False
        out = capsys.readouterr().out
        assert "Biblioteket" in out
        assert "0019" in out
        assert "aula widgets" in out

    @pytest.mark.asyncio
    async def test_require_widget_is_quiet_when_present(self, capsys):
        assert await _require_widget(self._client(["0019"]), "0019", "Biblioteket") is True
        assert capsys.readouterr().out == ""


class TestWidgetPreference:
    """MinUddannelse opgaver are reachable through more than one widget."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _WIDGET_ID_CACHE.clear()
        yield
        _WIDGET_ID_CACHE.clear()

    def _client(self, widget_ids, side_effect=None):
        client = MagicMock()
        widgets = [MagicMock(widget_id=wid) for wid in widget_ids]
        client.get_widgets = AsyncMock(return_value=widgets, side_effect=side_effect)
        return client

    @pytest.mark.asyncio
    async def test_prefers_the_first_widget_when_present(self):
        client = self._client(["0023", "0030", "0029"])

        assert await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS) == "0030"

    @pytest.mark.asyncio
    async def test_falls_back_when_only_the_sso_widget_is_listed(self):
        """The reported case: 0029, 0023, 0072 and 0138, but no 0030."""
        client = self._client(["0029", "0023", "0072", "0138"])

        assert await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS) == "0023"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_candidate_is_listed(self):
        client = self._client(["0128", "0142"])

        assert await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS) is None

    @pytest.mark.asyncio
    async def test_an_unreadable_list_falls_back_to_the_preferred_widget(self):
        """Same rule as _has_widget: try the call rather than refuse."""
        client = self._client([], side_effect=RuntimeError("boom"))

        assert await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS) == "0030"

    @pytest.mark.asyncio
    async def test_the_list_is_fetched_once(self):
        client = self._client(["0023"])

        await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS)
        await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS)

        assert client.get_widgets.await_count == 1

    @pytest.mark.asyncio
    async def test_require_any_widget_returns_the_usable_id(self, capsys):
        client = self._client(["0023"])

        assert await _require_any_widget(client, MIN_UDDANNELSE_TASK_WIDGETS, "Opgaver") == "0023"
        assert capsys.readouterr().out == ""

    @pytest.mark.asyncio
    async def test_require_any_widget_lists_every_candidate_when_none_is_present(self, capsys):
        client = self._client(["0128"])

        assert await _require_any_widget(client, MIN_UDDANNELSE_TASK_WIDGETS, "Opgaver") is None
        out = capsys.readouterr().out
        assert "Opgaver" in out
        assert "0030" in out
        assert "0023" in out
        assert "aula widgets" in out


class TestWithChild:
    """Providers that answer per child return rows with no child on them."""

    def _child(self):
        return Child(
            id=4727534,
            profile_id=2044021,
            name="Astrid",
            institution_name="Skole",
            profile_picture="",
        )

    def test_tags_a_row_with_the_child_it_was_fetched_for(self):
        row = dict(EasyIQHomework(id="hw-1", title="Dansk", subject="Dansk"))
        tagged = _with_child(row, self._child())
        assert tagged["child_id"] == 4727534
        assert tagged["child_name"] == "Astrid"

    def test_keeps_the_row_intact(self):
        row = dict(EasyIQHomework(id="hw-1", title="Dansk", subject="Dansk", activities="7-9F"))
        tagged = _with_child(row, self._child())
        assert tagged["id"] == "hw-1"
        assert tagged["subject"] == "Dansk"
        assert tagged["activities"] == "7-9F"

    def test_does_not_mutate_the_row(self):
        row = dict(EasyIQHomework(id="hw-1", title="Dansk"))
        _with_child(row, self._child())
        assert "child_id" not in row


class TestFetchContactPages:
    @pytest.mark.asyncio
    async def test_walks_every_page_until_a_short_one(self):
        fetch_page, calls = _pager(45)

        result = await _fetch_contact_pages(fetch_page)

        assert len(result) == 45
        assert calls == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_stops_on_first_empty_page_when_total_is_a_multiple(self):
        """A full last page can't be detected as final, so one extra call happens."""
        fetch_page, calls = _pager(40)

        result = await _fetch_contact_pages(fetch_page)

        assert len(result) == 40
        assert calls == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_single_page_makes_one_call(self):
        fetch_page, calls = _pager(5)

        result = await _fetch_contact_pages(fetch_page)

        assert len(result) == 5
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_explicit_page_fetches_only_that_page(self):
        fetch_page, calls = _pager(100)

        result = await _fetch_contact_pages(fetch_page, page=3)

        assert calls == [3]
        assert [item["id"] for item in result] == list(range(40, 60))

    @pytest.mark.asyncio
    async def test_warns_instead_of_looping_forever(self, capsys):
        """A server that never returns a short page must not spin indefinitely."""
        calls: list[int] = []

        async def always_full(page: int) -> list[dict]:
            calls.append(page)
            return [{"id": page}] * CONTACTS_PAGE_SIZE

        result = await _fetch_contact_pages(always_full)

        assert len(calls) == MAX_CONTACT_PAGES
        assert len(result) == MAX_CONTACT_PAGES * CONTACTS_PAGE_SIZE
        assert "may be incomplete" in capsys.readouterr().out


def _ctx(**obj) -> click.Context:
    ctx = click.Context(click.Command("aula"))
    ctx.obj = obj
    return ctx


class TestCredentialProviders:
    """MitID credentials come from a flag, an env var, or a prompt — in that order."""

    @pytest.mark.asyncio
    async def test_token_code_from_context_skips_the_prompt(self, monkeypatch):
        prompt = MagicMock()
        monkeypatch.setattr(click, "prompt", prompt)

        provide = _token_digits_provider(_ctx(MITID_TOKEN_CODE="123456"))

        assert await provide() == "123456"
        prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_code_falls_back_to_the_prompt(self, monkeypatch):
        monkeypatch.setattr(click, "prompt", MagicMock(return_value="654321"))

        provide = _token_digits_provider(_ctx(MITID_TOKEN_CODE=None))

        assert await provide() == "654321"

    @pytest.mark.asyncio
    async def test_password_from_context_skips_the_prompt(self, monkeypatch):
        prompt = MagicMock()
        monkeypatch.setattr(click, "prompt", prompt)

        provide = _password_provider(_ctx(MITID_PASSWORD="hunter2"))

        assert await provide() == "hunter2"
        prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_password_prompt_hides_input(self, monkeypatch):
        """A MitID password echoed into the terminal would linger in scrollback."""
        prompt = MagicMock(return_value="typed")
        monkeypatch.setattr(click, "prompt", prompt)

        provide = _password_provider(_ctx(MITID_PASSWORD=None))

        assert await provide() == "typed"
        assert prompt.call_args.kwargs["hide_input"] is True


class TestLogout:
    """Testing a login flow means being able to throw the cached session away."""

    def test_removes_the_stored_session(self, tmp_path, monkeypatch):
        """A cached session skips MitID entirely, so it has to go."""
        token_file = tmp_path / "tokens.json"
        token_file.write_text('{"tokens": {"access_token": "abc123"}}')
        monkeypatch.setattr(cli, "DEFAULT_TOKEN_FILE", token_file)

        result = CliRunner().invoke(logout, [], obj={"OUTPUT_FORMAT": "text"})

        assert result.exit_code == 0
        assert not token_file.exists()

    def test_says_so_when_there_was_no_session(self, tmp_path, monkeypatch):
        """Silence would read as a session removed, and send the user hunting."""
        monkeypatch.setattr(cli, "DEFAULT_TOKEN_FILE", tmp_path / "tokens.json")

        result = CliRunner().invoke(logout, [], obj={"OUTPUT_FORMAT": "text"})

        assert result.exit_code == 0
        assert "No stored session" in result.output

    def test_leaves_the_saved_username_alone(self, tmp_path, monkeypatch):
        """Retyping the MitID username on every test login is the thing being avoided."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"mitid_username": "tester"}')
        monkeypatch.setattr(cli, "DEFAULT_TOKEN_FILE", tmp_path / "tokens.json")
        monkeypatch.setattr(cli, "CONFIG_FILE", config_file)

        CliRunner().invoke(logout, [], obj={"OUTPUT_FORMAT": "text"})

        assert config_file.exists()


def _qr(data: str) -> qrcode.QRCode:
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make()
    return qr


class TestQrFrameSchedule:
    def test_lingers_on_the_first_half_before_the_swapping_starts(self):
        """The first code needs time to be scanned before it starts moving."""
        assert cli._frame_seconds(0) == 2.0
        assert cli._frame_seconds(1) == 1.0
        assert cli._frame_seconds(2) == 1.0


class TestQrDisplay:
    """The two codes are halves of one value, so both have to reach the app."""

    @pytest.fixture(autouse=True)
    def _fast_frames(self, monkeypatch):
        monkeypatch.setattr(cli, "_QR_FRAME_SECONDS", 0.01)
        monkeypatch.setattr(cli, "_QR_FIRST_FRAME_SECONDS", 0.02)
        _terminal_draws_blocks.cache_clear()

    @pytest.mark.asyncio
    async def test_alternates_both_halves_until_the_codes_are_read(self, monkeypatch, capsys):
        """MitID sends a pair once, but a half the app never sees blocks the login."""
        monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)
        display = cli._TerminalQRDisplay()

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
        monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)
        display = cli._TerminalQRDisplay()

        display.show(_qr("part-one"), _qr("part-two"))
        await asyncio.sleep(0.03)
        display.done()

        assert "\x1b[" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_keeps_every_frame_the_same_height(self, monkeypatch, capsys):
        """A block that changes height as the halves swap leaves art behind on screen."""
        monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)
        display = cli._TerminalQRDisplay()

        display.show(_qr("part-one"), _qr("part-two"))
        await asyncio.sleep(0.05)
        display.done()

        blocks = capsys.readouterr().out.split("QR code 1 of 2:")
        assert len(blocks) > 2
        assert len({block.count("\n") for block in blocks[1:-1]}) == 1

    def test_prints_each_pair_once_without_a_terminal(self, monkeypatch, capsys):
        """MitID repeats the codes every poll; a log file should not repeat them too."""
        monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
        display = cli._TerminalQRDisplay()

        display.show(_qr("part-one"), _qr("part-two"))
        display.show(_qr("part-one"), _qr("part-two"))

        assert capsys.readouterr().out.count("QR code 1 of 2") == 1

    def test_prints_a_new_pair_when_the_codes_rotate(self, monkeypatch, capsys):
        """MitID rotates the value, and only the current pair can be scanned."""
        monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
        display = cli._TerminalQRDisplay()

        display.show(_qr("part-one"), _qr("part-two"))
        display.show(_qr("part-one-v2"), _qr("part-two-v2"))

        assert capsys.readouterr().out.count("QR code 1 of 2") == 2

    def test_falls_back_to_ascii_when_blocks_cannot_be_encoded(self, monkeypatch):
        """A console that cannot print blocks would otherwise show a broken code."""
        monkeypatch.setattr(cli, "_terminal_draws_blocks", lambda: False)

        rendered = _render_qr(_qr("part-one"))

        assert rendered.isascii()
        assert "#" in rendered


class TestVersionFlag:
    def test_reports_the_version_and_the_python_it_runs_on(self):
        """Bug reports are read from a traceback, and both numbers are needed."""
        result = CliRunner().invoke(cli.cli, ["--version"])

        assert result.exit_code == 0
        assert __version__ in result.output
        assert platform.python_version() in result.output


class TestOtpDisplay:
    def test_prints_the_code(self, capsys):
        """App users who cannot scan need the code MitID expects them to type."""
        _print_otp_code("A1B2")

        assert "A1B2" in capsys.readouterr().out


class TestReportSick:
    """The sick report writes to Aula, so who it touches must be exact."""

    @staticmethod
    def _child(child_id: int, name: str) -> Child:
        return Child(
            id=child_id,
            profile_id=child_id + 1000,
            name=name,
            institution_name="Test School",
            profile_picture="",
        )

    @staticmethod
    def _config(child_id: int, permission: str) -> PresenceConfiguration:
        return PresenceConfiguration.from_dict(
            {
                "uniStudentId": child_id,
                "presenceConfiguration": {
                    "dashboardModuleSettings": [
                        {
                            "presenceDashboardContext": "guardian_dashboard",
                            "presenceModules": [
                                {"moduleType": "report_sick", "permission": permission}
                            ],
                        }
                    ]
                },
            }
        )

    @pytest.fixture
    def fake_client(self):
        """A client recording presence writes, with two children by default."""
        client = MagicMock()
        client.get_profile = AsyncMock(
            return_value=Profile(
                profile_id=1,
                display_name="Guardian",
                children=[self._child(201, "Alfa"), self._child(202, "Beta")],
            )
        )
        client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "editable"), self._config(202, "editable")]
        )
        client.get_daily_overview = AsyncMock(return_value=None)
        client.update_presence_status = AsyncMock(return_value=True)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    @pytest.fixture
    def run(self, fake_client, monkeypatch):
        """Invoke report-sick against the fake client."""
        monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=fake_client))

        def invoke(*args, output_format="text"):
            return CliRunner().invoke(report_sick, list(args), obj={"OUTPUT_FORMAT": output_format})

        return invoke

    def test_reports_every_child_sick(self, run, fake_client):
        result = run("-y")

        assert result.exit_code == 0
        fake_client.update_presence_status.assert_awaited_once_with([201, 202], PresenceState.SICK)

    def test_child_option_limits_the_write(self, run, fake_client):
        result = run("--child", "202", "-y")

        assert result.exit_code == 0
        fake_client.update_presence_status.assert_awaited_once_with([202], PresenceState.SICK)

    def test_undo_sets_not_present(self, run, fake_client):
        run("--undo", "-y")

        fake_client.update_presence_status.assert_awaited_once_with(
            [201, 202], PresenceState.NOT_PRESENT
        )

    def test_undo_present_sets_present(self, run, fake_client):
        run("--undo", "--present", "-y")

        fake_client.update_presence_status.assert_awaited_once_with(
            [201, 202], PresenceState.PRESENT
        )

    def test_present_without_undo_is_rejected(self, run, fake_client):
        result = run("--present", "-y")

        assert "--present only applies together with --undo" in result.output
        fake_client.update_presence_status.assert_not_awaited()

    def test_children_without_permission_are_skipped(self, run, fake_client):
        """An institution that withholds the module would reject the whole call."""
        fake_client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "editable"), self._config(202, "deactivated")]
        )

        result = run("-y")

        fake_client.update_presence_status.assert_awaited_once_with([201], PresenceState.SICK)
        assert "Beta" in result.output
        assert "not enabled" in result.output

    def test_read_only_permission_names_the_reason(self, run, fake_client):
        fake_client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "readable"), self._config(202, "readable")]
        )

        result = run("-y")

        fake_client.update_presence_status.assert_not_awaited()
        assert "read-only" in result.output

    def test_unreadable_configuration_does_not_block_the_write(self, run, fake_client):
        """Not being able to check permission is not the same as being denied."""
        fake_client.get_presence_configuration = AsyncMock(side_effect=RuntimeError("boom"))

        run("-y")

        fake_client.update_presence_status.assert_awaited_once_with([201, 202], PresenceState.SICK)

    def test_confirmation_prompt_can_cancel(self, run, fake_client, monkeypatch):
        monkeypatch.setattr(click, "confirm", MagicMock(return_value=False))

        result = run()

        assert "Cancelled." in result.output
        fake_client.update_presence_status.assert_not_awaited()

    def test_json_output_requires_yes(self, run, fake_client):
        """A scripted write must be explicit, since JSON mode cannot prompt."""
        result = run(output_format="json")

        assert "requires --yes" in result.output
        fake_client.update_presence_status.assert_not_awaited()

    def test_json_output_reports_updated_and_skipped(self, run, fake_client):
        fake_client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "editable"), self._config(202, "deactivated")]
        )

        result = run("-y", output_format="json")

        payload = json.loads(result.output)
        assert payload["status"] == "SICK"
        assert payload["status_value"] == 1
        assert payload["updated"] == [{"id": 201, "name": "Alfa"}]
        assert [s["id"] for s in payload["skipped"]] == [202]

    def test_no_children_writes_nothing(self, run, fake_client):
        fake_client.get_profile = AsyncMock(
            return_value=Profile(profile_id=1, display_name="Guardian", children=[])
        )

        run("-y")

        fake_client.update_presence_status.assert_not_awaited()

    def test_unknown_child_id_writes_nothing(self, run, fake_client):
        result = run("--child", "999", "-y")

        assert "no children found" in result.output
        fake_client.update_presence_status.assert_not_awaited()

    def test_api_failure_is_reported(self, run, fake_client):
        fake_client.update_presence_status = AsyncMock(side_effect=RuntimeError("403"))

        result = run("-y")

        assert "updating presence status" in result.output


class TestEasyiqPerChildInstitutionScoping:
    """A daycare child's institution must not be replaced by a sibling's school.

    Regression coverage for https://github.com/nickknissen/aula/issues/68: the
    family-wide institution filter was reused unchanged for every child, so
    EasyIQ answered every child with the oldest child's class.
    """

    @staticmethod
    def _child(child_id: int, user_id: str, inst_code: str) -> Child:
        raw: dict = {"userId": user_id}
        if inst_code:
            raw["institutionProfile"] = {"institutionCode": inst_code}
        return Child(
            id=child_id,
            profile_id=child_id + 1000,
            name=f"Child{child_id}",
            institution_name="Test School",
            profile_picture="",
            _raw=raw,
        )

    @staticmethod
    def _profile_context(child_user_ids: list[str]) -> dict:
        return {
            "data": {
                "userId": "guardian-session",
                "institutionProfile": {"relations": [{"userId": uid} for uid in child_user_ids]},
                "institutions": [],
            }
        }

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _WIDGET_ID_CACHE.clear()
        yield
        _WIDGET_ID_CACHE.clear()

    def _client(self, children: list[Child]) -> MagicMock:
        client = MagicMock()
        client.get_profile = AsyncMock(
            return_value=Profile(profile_id=1, display_name="Guardian", children=children)
        )
        client.get_widgets = AsyncMock(
            return_value=[
                MagicMock(widget_id=WIDGET_EASYIQ_WEEKPLAN),
                MagicMock(widget_id=WIDGET_EASYIQ_HOMEWORK),
            ]
        )
        client.get_profile_context = AsyncMock(
            return_value=self._profile_context([str(c._raw["userId"]) for c in children if c._raw])
        )
        client.widgets = MagicMock()
        client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[])
        client.widgets.get_easyiq_homework = AsyncMock(return_value=[])
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    def _run(self, command, client, monkeypatch, *args):
        monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=client))
        return CliRunner().invoke(command, list(args), obj={"OUTPUT_FORMAT": "text"})

    def test_ugeplan_scopes_institution_filter_per_child(self, monkeypatch):
        school_child = self._child(1, "u-school", "SCH-1")
        daycare_child = self._child(2, "u-daycare", "DAY-2")
        client = self._client([school_child, daycare_child])

        result = self._run(easyiq_ugeplan, client, monkeypatch)

        assert result.exit_code == 0
        calls = client.widgets.get_easyiq_weekplan.await_args_list
        assert len(calls) == 2
        assert calls[0].args[2] == ["SCH-1"]
        assert calls[1].args[2] == ["DAY-2"]
        assert calls[0].args[2] != calls[1].args[2]

    def test_ugeplan_passes_every_institution_for_the_portal_session(self, monkeypatch):
        """The session is cached, so it must be made under all institutions.

        Scoped per child it would depend on which child was read first, and
        children at the guardian's other institutions could then look like
        children EasyIQ does not know at all.
        """
        school_child = self._child(1, "u-school", "SCH-1")
        daycare_child = self._child(2, "u-daycare", "DAY-2")
        client = self._client([school_child, daycare_child])

        result = self._run(easyiq_ugeplan, client, monkeypatch)

        assert result.exit_code == 0
        calls = client.widgets.get_easyiq_weekplan.await_args_list
        for call_ in calls:
            assert call_.kwargs["all_institution_filter"] == ["SCH-1", "DAY-2"]

    def test_ugeplan_says_so_when_easyiq_has_no_record_of_a_child(self, monkeypatch):
        """A gap the user cannot see reads as a bug. Name it instead."""
        school_child = self._child(1, "u-school", "SCH-1")
        daycare_child = self._child(2, "u-daycare", "DAY-2")
        client = self._client([school_child, daycare_child])
        client.widgets.get_easyiq_weekplan = AsyncMock(
            side_effect=[[], EasyIQChildNotInPortal("no such child")]
        )

        result = self._run(easyiq_ugeplan, client, monkeypatch)

        assert result.exit_code == 0
        assert "No EasyIQ weekly plan for Child2" in result.output
        # Not phrased as a failure: it is the correct answer for that child.
        assert "Error:" not in result.output

    def test_ugeplan_falls_back_to_family_wide_filter_without_institution_code(self, monkeypatch):
        school_child = self._child(1, "u-school", "SCH-1")
        no_institution_child = self._child(2, "u-none", "")
        client = self._client([school_child, no_institution_child])

        result = self._run(easyiq_ugeplan, client, monkeypatch)

        assert result.exit_code == 0
        calls = client.widgets.get_easyiq_weekplan.await_args_list
        assert calls[0].args[2] == ["SCH-1"]
        # No institution code of its own: falls back to the family-wide list.
        assert calls[1].args[2] == ["SCH-1"]

    def test_homework_scopes_institution_filter_per_child(self, monkeypatch):
        school_child = self._child(1, "u-school", "SCH-1")
        daycare_child = self._child(2, "u-daycare", "DAY-2")
        client = self._client([school_child, daycare_child])

        result = self._run(easyiq_homework, client, monkeypatch)

        assert result.exit_code == 0
        calls = client.widgets.get_easyiq_homework.await_args_list
        assert len(calls) == 2
        assert calls[0].args[2] == ["SCH-1"]
        assert calls[1].args[2] == ["DAY-2"]
        assert calls[0].args[2] != calls[1].args[2]

    def test_homework_falls_back_to_family_wide_filter_without_institution_code(self, monkeypatch):
        school_child = self._child(1, "u-school", "SCH-1")
        no_institution_child = self._child(2, "u-none", "")
        client = self._client([school_child, no_institution_child])

        result = self._run(easyiq_homework, client, monkeypatch)

        assert result.exit_code == 0
        calls = client.widgets.get_easyiq_homework.await_args_list
        assert calls[0].args[2] == ["SCH-1"]
        assert calls[1].args[2] == ["SCH-1"]


def _make_task(
    *,
    title: str,
    weekday: str,
    student: str = "Barn Et",
    task_type: str = "SimpelLektie",
    classes: tuple[tuple[str, str], ...] = (("Dansk 3.1", "Dansk"),),
    course: str | None = None,
    deep_link: str | None = None,
    is_completed: bool = False,
    due_date=None,
) -> MUTask:
    return MUTask(
        id=title,
        title=title,
        task_type=task_type,
        due_date=due_date,
        weekday=weekday,
        week_number=34,
        is_completed=is_completed,
        student_name=student,
        unilogin="barn123",
        url="https://api.minuddannelse.net/aula/redirect/1/abc",
        deep_link=deep_link,
        classes=[
            MUTaskClass(id=1, name=name, subject_id=2, subject_name=subject)
            for name, subject in classes
        ],
        course=(
            MUTaskCourse(id="1", name=course, icon="", yearly_plan_id="", color=None, url=None)
            if course
            else None
        ),
    )


class TestMuTaskClasses:
    def test_adds_the_subject_when_it_is_not_in_the_class_name(self):
        task = _make_task(title="T", weekday="Mandag", classes=(("Bibliotek", "Andet"),))
        assert _mu_task_classes(task) == "Bibliotek (Andet)"

    def test_skips_a_subject_the_class_name_already_carries(self):
        task = _make_task(title="T", weekday="Mandag", classes=(("Historie 3.1", "Historie"),))
        assert _mu_task_classes(task) == "Historie 3.1"

    def test_joins_several_classes(self):
        task = _make_task(
            title="T",
            weekday="Mandag",
            classes=(("Dansk 3.1", "Dansk"), ("Matematik 3.1", "Matematik")),
        )
        assert _mu_task_classes(task) == "Dansk 3.1, Matematik 3.1"


class TestMuTaskRows:
    def test_repeated_day_is_only_shown_once(self):
        rows, _ = _mu_task_rows(
            [
                _make_task(title="En", weekday="Tirsdag"),
                _make_task(title="To", weekday="Tirsdag"),
                _make_task(title="Tre", weekday="Onsdag"),
            ]
        )

        assert [row[0] for row in rows] == ["Tirsdag", "", "Onsdag"]

    def test_links_become_numbered_footnotes(self):
        rows, links = _mu_task_rows(
            [
                _make_task(title="En", weekday="Tirsdag", deep_link="https://example.com/1"),
                _make_task(title="To", weekday="Tirsdag"),
                _make_task(title="Tre", weekday="Onsdag", deep_link="https://example.com/3"),
            ]
        )

        assert [row[1] for row in rows] == ["En [1]", "To", "Tre [2]"]
        assert links == ["https://example.com/1", "https://example.com/3"]

    def test_course_is_a_second_line_of_the_task_cell(self):
        rows, _ = _mu_task_rows(
            [_make_task(title="En", weekday="Tirsdag", course="Kirkens historie")]
        )

        assert rows[0][1] == "En\n  Course: Kirkens historie"

    def test_task_type_uses_the_portal_label(self):
        rows, _ = _mu_task_rows(
            [
                _make_task(title="En", weekday="Tirsdag"),
                _make_task(title="To", weekday="Tirsdag", task_type="Opgave"),
                _make_task(title="Tre", weekday="Tirsdag", task_type="NyType"),
            ]
        )

        assert [row[3] for row in rows] == ["Lektie", "Opgave", "NyType"]

    def test_completed_tasks_are_marked(self):
        rows, _ = _mu_task_rows(
            [
                _make_task(title="En", weekday="Tirsdag", is_completed=True),
                _make_task(title="To", weekday="Tirsdag"),
            ]
        )

        assert [row[4] for row in rows] == ["✓", ""]


class TestPrintMuTaskTables:
    def test_one_table_per_student_in_day_order(self, capsys, monkeypatch):
        monkeypatch.setattr("aula.utils.table._print_rows_with_rich", lambda *a: False)

        print_mu_task_tables(
            [
                _make_task(title="Fredagsopgave", weekday="Fredag", student="Barn To"),
                _make_task(title="Mandagsopgave", weekday="Mandag", student="Barn To"),
                _make_task(title="Onsdagsopgave", weekday="Onsdag", student="Barn Et"),
            ]
        )
        out = capsys.readouterr().out

        assert out.index("Barn Et") < out.index("Barn To")
        assert out.index("Mandagsopgave") < out.index("Fredagsopgave")

    def test_empty_columns_are_dropped(self, capsys, monkeypatch):
        monkeypatch.setattr("aula.utils.table._print_rows_with_rich", lambda *a: False)

        print_mu_task_tables([_make_task(title="En", weekday="Mandag")])
        out = capsys.readouterr().out

        assert "Day" in out
        assert "Done" not in out

    def test_links_are_listed_under_the_table(self, capsys, monkeypatch):
        monkeypatch.setattr("aula.utils.table._print_rows_with_rich", lambda *a: False)

        print_mu_task_tables(
            [_make_task(title="En", weekday="Mandag", deep_link="https://example.com/1")]
        )
        lines = capsys.readouterr().out.splitlines()

        assert lines[-1] == "  [1] https://example.com/1"
