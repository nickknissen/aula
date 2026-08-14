"""Tests for aula.cli helpers."""

import json
from unittest.mock import AsyncMock, MagicMock

import click
import pytest
from click.testing import CliRunner

from aula.cli import (
    _WIDGET_ID_CACHE,
    CONTACTS_PAGE_SIZE,
    MAX_CONTACT_PAGES,
    _fetch_contact_pages,
    _has_widget,
    _password_provider,
    _print_otp_code,
    _require_widget,
    _token_digits_provider,
    _with_child,
    report_sick,
)
from aula.models import (
    Child,
    EasyIQHomework,
    PresenceConfiguration,
    PresenceState,
    Profile,
)


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
