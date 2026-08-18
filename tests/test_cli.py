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
    _first_available_widget,
    _has_widget,
    _password_provider,
    _print_otp_code,
    _require_any_widget,
    _require_widget,
    _token_digits_provider,
    _with_child,
    debug_easyiq_child,
    easyiq_homework,
    easyiq_ugeplan,
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


class TestDebugEasyiqChild:
    """``debug:easyiq-child`` must be safe to paste into a public GitHub issue.

    Coverage for the debug command added alongside issue #68: the default
    output must never carry a child's name or the bearer token, no matter how
    the requests it inspects turned out.
    """

    BEARER_TOKEN = "super-secret-bearer-token"
    CHILD_NAME = "Emilie Testesen"

    @staticmethod
    def _child(child_id: int, user_id: str, name: str) -> Child:
        return Child(
            id=child_id,
            profile_id=child_id + 1000,
            name=name,
            institution_name="Test School",
            profile_picture="",
            _raw={"userId": user_id},
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

    @staticmethod
    def _calendar_response(payload) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=payload)
        return resp

    def _client(self, children: list[Child], *, calendar_rows: list[dict] | None = None):
        child_user_ids = [str((c._raw or {})["userId"]) for c in children]
        client = MagicMock()
        client.get_profile = AsyncMock(
            return_value=Profile(profile_id=1, display_name="Guardian", children=children)
        )
        client.get_profile_context = AsyncMock(return_value=self._profile_context(child_user_ids))
        client.widgets = MagicMock()
        client.widgets.ensure_easyiq_session = AsyncMock()
        client.widgets._get_bearer_token = AsyncMock(return_value=f"Bearer {self.BEARER_TOKEN}")
        client.widgets._easyiq_parent_login_id = None
        client.widgets.resolve_easyiq_child_login = MagicMock(return_value=None)
        client.widgets.resolve_easyiq_child_id = MagicMock(return_value=None)
        client.widgets.easyiq_identifier_variants = MagicMock(
            return_value=[("profile-id", "user-id")]
        )
        client.widgets.switch_easyiq_child = AsyncMock()

        def _headers(token, institution_filter, guardian_login, child_user_ids, child_user_id=""):
            return {
                "Authorization": token,
                "Accept": "application/json",
                "x-institutionfilter": ",".join(institution_filter),
                "x-login": guardian_login,
                "x-child": child_user_id,
                "x-childfilter": ",".join(child_user_ids),
            }

        client.widgets.easyiq_headers = MagicMock(side_effect=_headers)
        client._request_with_version_retry = AsyncMock(
            side_effect=[self._calendar_response(calendar_rows or []) for _ in children]
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    def _run(self, client, monkeypatch, *args):
        monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=client))
        return CliRunner().invoke(debug_easyiq_child, list(args), obj={"OUTPUT_FORMAT": "text"})

    def test_default_output_has_no_bearer_token_or_child_names(self, monkeypatch):
        children = [
            self._child(1, "u-one", self.CHILD_NAME),
            self._child(2, "u-two", "Anders Testesen"),
        ]
        client = self._client(
            children,
            calendar_rows=[{"Id": "1", "ItemType": 9, "ActivitiesDisplay": "6A"}],
        )

        result = self._run(client, monkeypatch)

        assert result.exit_code == 0
        assert self.BEARER_TOKEN not in result.output
        assert self.CHILD_NAME not in result.output
        assert "Anders Testesen" not in result.output
        assert "No child names, titles, descriptions or bearer token" in result.output

    def test_output_includes_the_overlap_matrix(self, monkeypatch):
        children = [self._child(1, "u-one", "A"), self._child(2, "u-two", "B")]
        client = self._client(children, calendar_rows=[{"Id": "1", "ItemType": 9}])

        result = self._run(client, monkeypatch)

        assert "Overlap matrix" in result.output

    def test_switch_child_flag_is_off_by_default(self, monkeypatch):
        children = [self._child(1, "u-one", "A")]
        client = self._client(children)
        client.widgets.resolve_easyiq_child_id = MagicMock(return_value="9001")

        self._run(client, monkeypatch)

        client.widgets.switch_easyiq_child.assert_not_awaited()

    def test_switch_child_flag_posts_switch_child_first(self, monkeypatch):
        children = [self._child(1, "u-one", "A")]
        client = self._client(children)
        client.widgets.resolve_easyiq_child_id = MagicMock(return_value="9001")

        result = self._run(client, monkeypatch, "--switch-child")

        assert result.exit_code == 0
        client.widgets.switch_easyiq_child.assert_awaited_once()

    def test_include_values_prints_titles_and_warns(self, monkeypatch):
        children = [self._child(1, "u-one", self.CHILD_NAME)]
        client = self._client(
            children,
            calendar_rows=[{"Id": "1", "ItemType": 9, "Courses": "Dansk"}],
        )

        result = self._run(client, monkeypatch, "--include-values")

        assert "Dansk" in result.output
        assert "Do not paste this publicly" in result.output

    def test_no_children_reports_empty(self, monkeypatch):
        client = self._client([])

        result = self._run(client, monkeypatch)

        assert "no children" in result.output.lower()
