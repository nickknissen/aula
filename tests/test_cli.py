"""Tests for aula.cli helpers."""

import datetime
import json
import logging
import platform
from unittest.mock import AsyncMock, MagicMock

import click
import pytest
from click.testing import CliRunner

from aula import __version__, cli
from aula.cli import (
    _WIDGET_ID_CACHE,
    CONTACTS_PAGE_SIZE,
    MAX_CONTACT_PAGES,
    _child_institution_filter,
    _fetch_contact_pages,
    _first_available_widget,
    _has_widget,
    _mu_task_classes,
    _mu_task_rows,
    _password_provider,
    _print_otp_code,
    _require_any_widget,
    _require_widget,
    _resolve_week,
    _token_digits_provider,
    _with_child,
    easyiq_homework,
    easyiq_ugeplan,
    logout,
    print_mu_task_tables,
    register_absence,
    report_sick,
    vacations,
    weekly_summary,
)
from aula.const import (
    EASYIQ_WEEKPLAN_WIDGETS,
    MIN_UDDANNELSE_TASK_WIDGETS,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_EASYIQ_LEGACY,
    WIDGET_EASYIQ_WEEKPLAN,
)
from aula.http import AulaRejectedError
from aula.models import (
    Child,
    CommonFile,
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
    """Some providers are reachable through more than one widget."""

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

    @pytest.mark.asyncio
    async def test_easyiq_prefers_the_dedicated_weekplan_widget(self):
        client = self._client(
            [WIDGET_EASYIQ_HOMEWORK, WIDGET_EASYIQ_LEGACY, WIDGET_EASYIQ_WEEKPLAN]
        )

        assert (
            await _first_available_widget(client, EASYIQ_WEEKPLAN_WIDGETS) == WIDGET_EASYIQ_WEEKPLAN
        )

    @pytest.mark.asyncio
    async def test_easyiq_falls_back_to_the_legacy_widget(self):
        client = self._client([WIDGET_EASYIQ_HOMEWORK, WIDGET_EASYIQ_LEGACY])

        assert (
            await _first_available_widget(client, EASYIQ_WEEKPLAN_WIDGETS) == WIDGET_EASYIQ_LEGACY
        )

    @pytest.mark.asyncio
    async def test_easyiq_uses_the_homework_widget_as_the_last_verified_candidate(self):
        client = self._client([WIDGET_EASYIQ_HOMEWORK])

        assert (
            await _first_available_widget(client, EASYIQ_WEEKPLAN_WIDGETS) == WIDGET_EASYIQ_HOMEWORK
        )

    @pytest.mark.asyncio
    async def test_easyiq_reports_when_no_verified_candidate_is_available(self, capsys):
        client = self._client(["0019"])

        assert await _require_any_widget(client, EASYIQ_WEEKPLAN_WIDGETS, "EasyIQ Ugeplan") is None
        out = capsys.readouterr().out
        assert WIDGET_EASYIQ_WEEKPLAN in out
        assert WIDGET_EASYIQ_LEGACY in out
        assert WIDGET_EASYIQ_HOMEWORK in out

    @pytest.mark.asyncio
    async def test_easyiq_unreadable_widget_list_optimistically_uses_the_preferred_id(self):
        client = self._client([], side_effect=RuntimeError("boom"))

        assert (
            await _first_available_widget(client, EASYIQ_WEEKPLAN_WIDGETS) == WIDGET_EASYIQ_WEEKPLAN
        )


class TestWithChild:
    """Providers that answer per child return rows with no child on them."""

    def _child(self):
        return Child(
            id=1000001,
            profile_id=2000001,
            name="Barn Et",
            institution_name="Skole",
            profile_picture="",
        )

    def test_tags_a_row_with_the_child_it_was_fetched_for(self):
        row = dict(EasyIQHomework(id="hw-1", title="Dansk", subject="Dansk"))
        tagged = _with_child(row, self._child())
        assert tagged["child_id"] == 1000001
        assert tagged["child_name"] == "Barn Et"

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


class TestChildInstitutionFilter:
    """A per-child provider read is scoped to that child's own institution."""

    FAMILY = ["SKOLE-1", "SKOLE-2"]

    @staticmethod
    def _child(**fields) -> Child:
        return Child.from_dict({"id": 1, "profileId": 2, "name": "Barn Et", **fields})

    def test_uses_the_childs_own_institution(self):
        child = self._child(institutionProfile={"institutionCode": "SKOLE-2"})
        assert _child_institution_filter(child, self.FAMILY) == ["SKOLE-2"]

    def test_stringifies_a_numeric_institution_code(self):
        """Aula sometimes sends the code as a number; widget filters take strings."""
        child = self._child(institutionProfile={"institutionCode": 280001})
        assert _child_institution_filter(child, self.FAMILY) == ["280001"]

    def test_falls_back_for_a_child_built_without_raw_data(self):
        child = Child(id=1, profile_id=2, name="Barn Et", institution_name="", profile_picture="")
        assert _child_institution_filter(child, self.FAMILY) == self.FAMILY

    @pytest.mark.parametrize(
        "fields",
        [{}, {"institutionProfile": None}, {"institutionProfile": {"institutionName": "Skole"}}],
        ids=["no-institution-profile", "null-institution-profile", "no-institution-code"],
    )
    def test_falls_back_without_institution_data(self, fields):
        assert _child_institution_filter(self._child(**fields), self.FAMILY) == self.FAMILY

    def test_falls_back_on_an_empty_institution_code(self):
        child = self._child(institutionProfile={"institutionCode": ""})
        assert _child_institution_filter(child, self.FAMILY) == self.FAMILY

    def test_mutates_neither_the_child_nor_the_fallback(self):
        """The fallback is the family-wide list, shared by every child's read."""
        raw = {"id": 1, "profileId": 2, "name": "Barn To", "institutionProfile": {}}
        child = Child.from_dict(raw)
        fallback = list(self.FAMILY)

        _child_institution_filter(child, fallback).append("SKOLE-3")

        assert fallback == self.FAMILY
        assert raw == {"id": 1, "profileId": 2, "name": "Barn To", "institutionProfile": {}}
        assert child.institution_code is None


class TestResolveWeek:
    """Around New Year the ISO week belongs to a different year than the date."""

    @pytest.mark.parametrize(
        ("today", "week", "expected"),
        [
            (datetime.date(2026, 3, 4), None, "2026-W10"),
            (datetime.date(2027, 1, 1), None, "2026-W53"),
            (datetime.date(2025, 12, 29), None, "2026-W1"),
            (datetime.date(2027, 1, 2), "53", "2026-W53"),
            (datetime.date(2027, 1, 2), "2027-W1", "2027-W1"),
        ],
        ids=["mid-year", "new-year-in-last-week", "december-in-first-week", "bare-number", "full"],
    )
    def test_uses_the_iso_week_year(self, monkeypatch, today, week, expected):
        monkeypatch.setattr("aula.cli.aula_today", lambda: today)
        assert _resolve_week(week) == expected


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


class FakeMitID:
    """Stands in for ``aula.auth_flow.authenticate``, the MitID boundary."""

    def __init__(self, identities: list[str] | None = None):
        self.identities = identities or ["Parent"]
        self.logins = 0
        self.chosen_index: int | None = None

    async def __call__(
        self,
        username,
        token_storage,
        on_qr_codes=None,
        on_login_required=None,
        *_args,
        force_login=False,
        on_identity_selected=None,
        **_kwargs,
    ):
        saved = None if force_login else await token_storage.load()
        if saved:
            return saved
        self.logins += 1
        if on_login_required:
            on_login_required()
        if len(self.identities) > 1:
            assert on_identity_selected is not None
            self.chosen_index = await on_identity_selected(self.identities)
        token_data = {"tokens": {"access_token": "fresh"}, "cookies": {}}
        await token_storage.save(token_data)
        return token_data


class FakeAulaClient:
    api_url = "https://www.aula.dk/api/v25"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None


class TestLoginDrivenByAnotherProgram:
    """A program that leaves MitID to `aula login` picks the file, identity and timing."""

    @pytest.fixture
    def default_token_file(self, tmp_path, monkeypatch):
        path = tmp_path / "default" / "tokens.json"
        monkeypatch.setattr(cli, "DEFAULT_TOKEN_FILE", path)
        return path

    @pytest.fixture
    def run(self, monkeypatch, default_token_file):
        def run(*args, mitid: FakeMitID | None = None, env: dict[str, str] | None = None):
            monkeypatch.setattr("aula.auth_flow.authenticate", mitid or FakeMitID())
            monkeypatch.setattr(
                "aula.auth_flow.create_client", AsyncMock(return_value=FakeAulaClient())
            )
            clean_env = {"AULA_TOKEN_FILE": None, "AULA_MITID_IDENTITY": None, "AULA_OUTPUT": None}
            # The cli group reconfigures logging for the whole process, which
            # would silence the log assertions of tests that run after this one.
            root = logging.getLogger()
            level, handlers = root.level, root.handlers[:]
            try:
                return CliRunner().invoke(
                    cli.cli, ["--username", "tester", *args], env={**clean_env, **(env or {})}
                )
            finally:
                root.setLevel(level)
                root.handlers[:] = handlers

        return run

    def test_login_writes_only_the_given_token_file(self, run, tmp_path, default_token_file):
        token_file = tmp_path / "t.json"

        result = run("--token-file", str(token_file), "login")

        assert result.exit_code == 0, result.output
        assert token_file.exists()
        assert not default_token_file.exists()

    def test_logout_removes_the_given_token_file(self, run, tmp_path, default_token_file):
        token_file = tmp_path / "t.json"
        token_file.write_text('{"tokens": {"access_token": "abc123"}}')
        default_token_file.parent.mkdir()
        default_token_file.write_text('{"tokens": {"access_token": "other"}}')

        result = run("--token-file", str(token_file), "logout")

        assert result.exit_code == 0, result.output
        assert not token_file.exists()
        assert default_token_file.exists()
        assert str(token_file) in result.output

    def test_identity_is_picked_without_a_prompt(self, run, monkeypatch):
        monkeypatch.setattr(click, "prompt", MagicMock(side_effect=AssertionError("prompted")))
        mitid = FakeMitID(identities=["Parent (Privat)", "Parent (Firma ApS)"])

        result = run("--identity", "2", "login", mitid=mitid)

        assert result.exit_code == 0, result.output
        assert mitid.chosen_index == 1

    def test_identity_beyond_the_last_one_is_an_error(self, run, tmp_path):
        """Falling back to another identity would log in as the wrong person or company."""
        token_file = tmp_path / "t.json"
        mitid = FakeMitID(identities=["Parent (Privat)", "Parent (Firma ApS)"])

        result = run("--token-file", str(token_file), "--identity", "5", "login", mitid=mitid)

        assert result.exit_code == 2, result.output
        assert "Invalid value for '--identity'" in result.output
        assert "2 MitID identities" in result.output
        assert not token_file.exists()

    def test_force_logs_in_through_mitid_despite_a_saved_session(self, run, tmp_path):
        token_file = tmp_path / "t.json"
        token_file.write_text('{"tokens": {"access_token": "saved"}, "cookies": {}}')
        mitid = FakeMitID()

        result = run("--token-file", str(token_file), "login", "--force", mitid=mitid)

        assert result.exit_code == 0, result.output
        assert mitid.logins == 1
        assert json.loads(token_file.read_text())["tokens"]["access_token"] == "fresh"

    @staticmethod
    def _login_json(result) -> dict:
        # The MitID login notice shares stdout, so the JSON is the last line.
        return json.loads(result.stdout.splitlines()[-1])

    def test_json_output_names_the_chosen_identity(self, run):
        mitid = FakeMitID(identities=["Parent (Privat)", "Parent (Firma ApS)"])

        result = run("--output", "json", "--identity", "2", "login", mitid=mitid)

        assert result.exit_code == 0, result.output
        assert self._login_json(result) == {
            "status": "ok",
            "api_url": "https://www.aula.dk/api/v25",
            "identity": 2,
        }

    def test_json_output_leaves_identity_out_when_there_was_no_choice(self, run):
        result = run("--output", "json", "login")

        assert result.exit_code == 0, result.output
        assert "identity" not in self._login_json(result)

    def test_identity_beyond_a_single_identity_logs_in_with_a_warning(self, run):
        """MitID shows no choice for one identity, so the request could not be honoured."""
        result = run("--output", "json", "--identity", "2", "login")

        assert result.exit_code == 0, result.output
        assert "--identity 2" in result.stderr
        assert "identity" not in self._login_json(result)

    def test_identity_is_not_warned_about_when_a_saved_session_is_reused(self, run, tmp_path):
        token_file = tmp_path / "t.json"
        token_file.write_text('{"tokens": {"access_token": "saved"}, "cookies": {}}')

        result = run("--token-file", str(token_file), "--identity", "2", "login")

        assert result.exit_code == 0, result.output
        assert result.stderr == ""

    def test_text_output_names_the_chosen_identity(self, run):
        mitid = FakeMitID(identities=["Parent (Privat)", "Parent (Firma ApS)"])

        result = run("--identity", "2", "login", mitid=mitid)

        assert result.exit_code == 0, result.output
        assert "MitID identity 2" in result.output

    def test_environment_variables_stand_in_for_the_flags(self, run, tmp_path):
        token_file = tmp_path / "t.json"
        mitid = FakeMitID(identities=["Parent (Privat)", "Parent (Firma ApS)"])

        result = run(
            "login",
            mitid=mitid,
            env={"AULA_TOKEN_FILE": str(token_file), "AULA_MITID_IDENTITY": "2"},
        )

        assert result.exit_code == 0, result.output
        assert token_file.exists()
        assert mitid.chosen_index == 1


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


class TestRegisterAbsence:
    """The planned-absence write: which children, which dates, and only after consent."""

    TODAY = datetime.date(2026, 11, 11)
    DATES = ("--from", "2026-11-16", "--to", "2026-11-20")

    @staticmethod
    def _child(child_id: int, name: str, custody: bool | None = None) -> Child:
        raw = {} if custody is None else {"hasCustodyOrExtendedAccess": custody}
        return Child(
            id=child_id,
            profile_id=child_id + 1000,
            name=name,
            institution_name="Test Institution",
            profile_picture="",
            _raw=raw,
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
                                {"moduleType": "vacation", "permission": permission}
                            ],
                        }
                    ]
                },
            }
        )

    @pytest.fixture
    def fake_client(self):
        """A client recording absence writes, with two editable children by default."""
        client = MagicMock()
        client.get_profile = AsyncMock(
            return_value=Profile(
                profile_id=1,
                display_name="Guardian",
                children=[self._child(201, "Barn Et"), self._child(202, "Barn To")],
            )
        )
        client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "editable"), self._config(202, "editable")]
        )
        client.add_vacation = AsyncMock(return_value=True)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    @pytest.fixture
    def run(self, fake_client, monkeypatch):
        """Invoke register-absence against the fake client, on a fixed today."""
        monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=fake_client))
        monkeypatch.setattr("aula.cli.aula_today", lambda: self.TODAY)

        def invoke(*args, output_format="text", input=None):
            return CliRunner().invoke(
                register_absence,
                list(args),
                obj={"OUTPUT_FORMAT": output_format},
                input=input,
            )

        return invoke

    def test_registers_every_child_by_default(self, run, fake_client):
        result = run(*self.DATES, "-y")

        assert result.exit_code == 0
        fake_client.add_vacation.assert_awaited_once_with(
            [201, 202], datetime.date(2026, 11, 16), datetime.date(2026, 11, 20), ""
        )

    def test_child_option_limits_the_write(self, run, fake_client):
        run("--child", "202", *self.DATES, "-y")

        assert fake_client.add_vacation.await_args.args[0] == [202]

    def test_child_option_can_be_repeated(self, run, fake_client):
        fake_client.get_profile.return_value.children.append(self._child(203, "Barn Tre"))

        run("--child", "201", "--child", "203", *self.DATES, "-y")

        assert fake_client.add_vacation.await_args.args[0] == [201, 203]

    def test_comment_is_sent_unchanged(self, run, fake_client):
        run(*self.DATES, "--comment", "Familietur til Bornholm", "-y")

        assert fake_client.add_vacation.await_args.args[3] == "Familietur til Bornholm"

    def test_single_day_starting_today_is_accepted(self, run, fake_client):
        """Today is the earliest start the portal allows, and one day is a valid range."""
        result = run("--from", "2026-11-11", "--to", "2026-11-11", "-y")

        assert result.exit_code == 0
        fake_client.add_vacation.assert_awaited_once()

    def test_end_one_calendar_year_after_start_is_accepted(self, run, fake_client):
        result = run("--from", "2026-11-16", "--to", "2027-11-16", "-y")

        assert result.exit_code == 0
        fake_client.add_vacation.assert_awaited_once()

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (("--from", "2026-11-10", "--to", "2026-11-12"), "in the past"),
            (("--from", "2026-11-20", "--to", "2026-11-16"), "before start date"),
            (("--from", "2026-11-16", "--to", "2027-11-17"), "more than a year"),
            (("--from", "2028-02-29", "--to", "2029-03-01"), "latest 2029-02-28"),
            (("--from", "2026-11-16", "--to", "2026-11-16", "--comment", "x" * 251), "251"),
        ],
        ids=["past start", "reversed", "over a year", "leap day", "long comment"],
    )
    def test_invalid_absence_is_rejected_before_logging_in(
        self, run, fake_client, monkeypatch, args, message
    ):
        """Nothing about a refused absence should reach Aula, not even the login."""
        get_client = AsyncMock(return_value=fake_client)
        monkeypatch.setattr("aula.cli._get_client", get_client)

        result = run(*args, "-y")

        assert result.exit_code == 1
        assert message in result.output
        get_client.assert_not_awaited()
        fake_client.add_vacation.assert_not_awaited()

    def test_250_character_comment_is_accepted(self, run, fake_client):
        result = run(*self.DATES, "--comment", "x" * 250, "-y")

        assert result.exit_code == 0
        fake_client.add_vacation.assert_awaited_once()

    def test_impossible_calendar_date_is_rejected(self, run, fake_client):
        result = run("--from", "2027-02-30", "--to", "2027-03-02", "-y")

        assert result.exit_code == 2
        fake_client.add_vacation.assert_not_awaited()

    def test_dates_are_required(self, run, fake_client):
        result = run("--from", "2026-11-16", "-y")

        assert result.exit_code == 2
        assert "--to" in result.output
        fake_client.add_vacation.assert_not_awaited()

    def test_unknown_child_id_writes_nothing(self, run, fake_client):
        """A mistyped ID must not quietly shrink the write to the IDs that matched."""
        result = run("--child", "201", "--child", "999", *self.DATES, "-y")

        assert result.exit_code == 1
        assert "999" in result.output
        fake_client.add_vacation.assert_not_awaited()

    def test_no_children_writes_nothing(self, run, fake_client):
        fake_client.get_profile = AsyncMock(
            return_value=Profile(profile_id=1, display_name="Guardian", children=[])
        )

        result = run(*self.DATES, "-y")

        assert result.exit_code == 1
        fake_client.add_vacation.assert_not_awaited()

    def test_child_without_vacation_permission_is_skipped(self, run, fake_client):
        """Only the eligible child is sent, so Aula does not reject the whole call."""
        fake_client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "editable"), self._config(202, "deactivated")]
        )

        result = run(*self.DATES, "-y")

        assert fake_client.add_vacation.await_args.args[0] == [201]
        assert "Barn To" in result.output
        assert "not enabled absence registration" in result.output

    def test_read_only_permission_names_the_reason(self, run, fake_client):
        fake_client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "editable"), self._config(202, "readable")]
        )

        result = run(*self.DATES, "-y")

        assert fake_client.add_vacation.await_args.args[0] == [201]
        assert "read-only" in result.output

    def test_child_without_custody_is_skipped(self, run, fake_client):
        """The portal hides children the guardian has neither custody of nor extended access to."""
        fake_client.get_profile.return_value.children[1] = self._child(202, "Barn To", False)

        result = run(*self.DATES, "-y")

        assert fake_client.add_vacation.await_args.args[0] == [201]
        assert "no custody" in result.output

    def test_custody_flag_true_or_missing_is_not_a_denial(self, run, fake_client):
        fake_client.get_profile.return_value.children[0] = self._child(201, "Barn Et", True)

        run(*self.DATES, "-y")

        assert fake_client.add_vacation.await_args.args[0] == [201, 202]

    def test_all_children_blocked_writes_nothing(self, run, fake_client):
        fake_client.get_profile.return_value.children[0] = self._child(201, "Barn Et", False)
        fake_client.get_presence_configuration = AsyncMock(
            return_value=[self._config(202, "deactivated")]
        )

        result = run(*self.DATES, "-y")

        assert result.exit_code == 1
        fake_client.add_vacation.assert_not_awaited()

    def test_unreadable_configuration_leaves_the_decision_to_aula(self, run, fake_client, caplog):
        """Not being able to check permission is not the same as being denied."""
        fake_client.get_presence_configuration = AsyncMock(side_effect=RuntimeError("boom"))

        with caplog.at_level(logging.WARNING, logger="aula.cli"):
            result = run(*self.DATES, "-y")

        fake_client.add_vacation.assert_awaited_once()
        assert fake_client.add_vacation.await_args.args[0] == [201, 202]
        assert "skipped" not in result.output
        assert "Could not fetch presence configuration" in caplog.text

    def test_child_missing_from_configuration_is_sent_with_a_warning(
        self, run, fake_client, caplog
    ):
        fake_client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "editable")]
        )

        with caplog.at_level(logging.WARNING, logger="aula.cli"):
            result = run(*self.DATES, "-y")

        assert fake_client.add_vacation.await_args.args[0] == [201, 202]
        assert "skipped" not in result.output
        assert "No presence configuration for child 202" in caplog.text

    def test_confirmation_shows_children_dates_and_comment(self, run, fake_client):
        result = run(*self.DATES, "--comment", "Familietur", input="y\n")

        assert result.exit_code == 0
        for expected in ("Barn Et", "Barn To", "2026-11-16", "2026-11-20", "Familietur"):
            assert expected in result.output
        fake_client.add_vacation.assert_awaited_once()

    def test_declining_the_confirmation_writes_nothing(self, run, fake_client):
        result = run(*self.DATES, input="n\n")

        assert result.exit_code == 0
        assert "Cancelled." in result.output
        fake_client.add_vacation.assert_not_awaited()

    def test_json_output_requires_yes(self, run, fake_client):
        """A scripted write must be explicit, since JSON mode cannot prompt."""
        result = run(*self.DATES, output_format="json")

        assert result.exit_code == 1
        assert "requires --yes" in result.stderr
        assert result.stdout == ""
        fake_client.add_vacation.assert_not_awaited()

    def test_json_output_reports_registered_and_skipped(self, run, fake_client):
        fake_client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "editable"), self._config(202, "deactivated")]
        )

        result = run(*self.DATES, "--comment", "Familietur", "-y", output_format="json")

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["start_date"] == "2026-11-16"
        assert payload["end_date"] == "2026-11-20"
        assert payload["comment"] == "Familietur"
        assert payload["registered"] == [{"id": 201, "name": "Barn Et"}]
        assert [s["id"] for s in payload["skipped"]] == [202]
        assert payload["skipped"][0]["reason"]

    def test_json_output_stays_parseable_when_all_are_blocked(self, run, fake_client):
        fake_client.get_presence_configuration = AsyncMock(
            return_value=[self._config(201, "readable"), self._config(202, "deactivated")]
        )

        result = run(*self.DATES, "-y", output_format="json")

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["registered"] == []
        assert [s["id"] for s in payload["skipped"]] == [201, 202]
        fake_client.add_vacation.assert_not_awaited()

    def test_write_failure_is_reported_as_failure(self, run, fake_client):
        fake_client.add_vacation = AsyncMock(
            side_effect=AulaRejectedError("Aula rejected calendar.addVacation", 200, code=10)
        )

        result = run(*self.DATES, "-y")

        assert result.exit_code == 1
        assert "registering absence" in result.output
        assert "✓" not in result.output

    def test_write_failure_in_json_mode_keeps_stdout_clean(self, run, fake_client):
        fake_client.add_vacation = AsyncMock(side_effect=RuntimeError("HTTP 500"))

        result = run(*self.DATES, "-y", output_format="json")

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "registering absence" in result.stderr

    def test_vacations_reader_does_not_write(self, fake_client, monkeypatch):
        """The existing reader keeps reading institution registrations only."""
        fake_client.get_vacation_registrations = AsyncMock(return_value=[])
        monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=fake_client))

        result = CliRunner().invoke(vacations, [], obj={"OUTPUT_FORMAT": "text"})

        assert result.exit_code == 0
        fake_client.get_vacation_registrations.assert_awaited_once_with([201, 202])
        fake_client.add_vacation.assert_not_awaited()


class TestEasyiqPerChildInstitutionScoping:
    """A daycare child's institution must not be replaced by a sibling's school.

    Regression coverage for https://github.com/nickknissen/aula/issues/68: the
    family-wide institution filter was reused unchanged for every child, so
    EasyIQ answered every child with the oldest child's class.
    """

    @staticmethod
    def _child(child_id: int, user_id: str, inst_code: str) -> Child:
        institution: dict = {"institutionName": "Test School"}
        if inst_code:
            institution["institutionCode"] = inst_code
        return Child.from_dict(
            {
                "id": child_id,
                "profileId": child_id + 1000,
                "name": f"Child{child_id}",
                "userId": user_id,
                "institutionProfile": institution,
            }
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
            return_value=self._profile_context([c.user_id for c in children if c.user_id])
        )
        client.widgets = MagicMock()
        client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[])
        client.widgets.get_easyiq_homework = AsyncMock(return_value=[])
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    def _run(self, command, client, monkeypatch, *args, output_format="text"):
        monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=client))
        return CliRunner().invoke(command, list(args), obj={"OUTPUT_FORMAT": output_format})

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
        assert all(call_.kwargs["widget_id"] == WIDGET_EASYIQ_WEEKPLAN for call_ in calls)

    def test_ugeplan_json_uses_the_selected_legacy_widget(self, monkeypatch):
        child = self._child(1, "u-school", "SCH-1")
        client = self._client([child])
        client.get_widgets = AsyncMock(return_value=[MagicMock(widget_id=WIDGET_EASYIQ_LEGACY)])

        result = self._run(
            easyiq_ugeplan,
            client,
            monkeypatch,
            output_format="json",
        )

        assert result.exit_code == 0
        calls = client.widgets.get_easyiq_weekplan.await_args_list
        assert len(calls) == 1
        assert calls[0].kwargs["widget_id"] == WIDGET_EASYIQ_LEGACY

    def test_weekly_summary_uses_the_selected_legacy_widget(self, monkeypatch):
        child = self._child(1, "u-school", "SCH-1")
        client = self._client([child])
        client.get_widgets = AsyncMock(return_value=[MagicMock(widget_id=WIDGET_EASYIQ_LEGACY)])
        client.get_calendar_events = AsyncMock(return_value=[])
        client.get_message_threads = AsyncMock(return_value=[])

        result = self._run(
            weekly_summary,
            client,
            monkeypatch,
            "--provider",
            "easyiq",
        )

        assert result.exit_code == 0
        client.widgets.get_easyiq_weekplan.assert_awaited_once()
        assert (
            client.widgets.get_easyiq_weekplan.await_args.kwargs["widget_id"]
            == WIDGET_EASYIQ_LEGACY
        )

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

    @pytest.mark.parametrize(
        ("command", "args", "reader", "output_format"),
        [
            (easyiq_ugeplan, [], "get_easyiq_weekplan", "json"),
            (easyiq_homework, [], "get_easyiq_homework", "json"),
            (weekly_summary, ["--provider", "easyiq"], "get_easyiq_weekplan", "text"),
            (weekly_summary, ["--provider", "easyiq_homework"], "get_easyiq_homework", "text"),
        ],
        ids=["ugeplan-json", "homework-json", "summary-weekplan", "summary-homework"],
    )
    def test_every_per_child_read_scopes_its_institution(
        self, monkeypatch, command, args, reader, output_format
    ):
        """The JSON and weekly-summary paths read per child just like the text paths."""
        children = [
            self._child(1, "u-school", "SCH-1"),
            self._child(2, "u-daycare", "DAY-2"),
            self._child(3, "u-none", ""),
        ]
        client = self._client(children)
        client.get_calendar_events = AsyncMock(return_value=[])
        client.get_message_threads = AsyncMock(return_value=[])

        result = self._run(command, client, monkeypatch, *args, output_format=output_format)

        assert result.exit_code == 0
        calls = getattr(client.widgets, reader).await_args_list
        assert [call_.args[2] for call_ in calls] == [["SCH-1"], ["DAY-2"], ["SCH-1", "DAY-2"]]
        for call_ in calls:
            assert call_.kwargs["all_institution_filter"] == ["SCH-1", "DAY-2"]


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


class TestMarkRead:
    @pytest.fixture
    def fake_client(self):
        client = MagicMock()
        client.mark_thread_read = AsyncMock(return_value=True)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    @pytest.fixture
    def run(self, fake_client, monkeypatch):
        monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=fake_client))

        def invoke(*args, output_format="text"):
            return CliRunner().invoke(
                cli.mark_read, list(args), obj={"OUTPUT_FORMAT": output_format}
            )

        return invoke

    def test_marks_every_thread_given(self, run, fake_client):
        result = run("1", "2")

        assert result.exit_code == 0
        assert [c.args for c in fake_client.mark_thread_read.await_args_list] == [("1",), ("2",)]
        assert "✓ 1" in result.output
        assert "✓ 2" in result.output

    def test_a_failing_thread_is_reported_and_the_rest_still_run(self, run, fake_client):
        fake_client.mark_thread_read = AsyncMock(side_effect=[RuntimeError("boom"), True])

        result = run("1", "2")

        assert result.exit_code == 1
        assert "✗ 1" in result.output
        assert "✓ 2" in result.output
        assert "boom" in result.output

    def test_a_thread_with_nothing_to_mark_fails_the_command(self, run, fake_client):
        fake_client.mark_thread_read = AsyncMock(return_value=False)

        result = run("1")

        assert result.exit_code == 1
        assert "✗ 1" in result.output

    def test_json_output_stays_valid_when_a_thread_fails(self, run, fake_client):
        fake_client.mark_thread_read = AsyncMock(side_effect=[RuntimeError("boom"), True])

        result = run("1", "2", output_format="json")

        assert result.exit_code == 1
        assert json.loads(result.stdout) == [
            {"thread_id": "1", "marked": False},
            {"thread_id": "2", "marked": True},
        ]
        assert "boom" in result.stderr
        assert "boom" not in result.stdout

    def test_a_refused_thread_is_followed_by_a_marked_one(self, run, fake_client):
        fake_client.mark_thread_read = AsyncMock(side_effect=[ValueError("common inbox"), True])

        result = run("1", "2")

        assert result.exit_code == 1
        assert "✗ 1" in result.output
        assert "✓ 2" in result.output

    def test_json_output_when_every_thread_is_marked(self, run):
        result = run("1", "2", output_format="json")

        assert result.exit_code == 0
        assert json.loads(result.stdout) == [
            {"thread_id": "1", "marked": True},
            {"thread_id": "2", "marked": True},
        ]

    def test_json_output_when_every_thread_fails(self, run, fake_client):
        fake_client.mark_thread_read = AsyncMock(side_effect=RuntimeError("boom"))

        result = run("1", "2", output_format="json")

        assert result.exit_code == 1
        assert json.loads(result.stdout) == [
            {"thread_id": "1", "marked": False},
            {"thread_id": "2", "marked": False},
        ]
        assert result.stderr.count("boom") == 2

    def test_needs_a_thread_id(self, run):
        assert run().exit_code != 0


class TestCommonFiles:
    @staticmethod
    def _child(child_id, institution_code):
        return Child.from_dict(
            {
                "id": child_id,
                "profileId": child_id + 100,
                "name": f"Barn {child_id}",
                "institutionProfile": {"institutionCode": institution_code},
            }
        )

    @pytest.fixture
    def fake_client(self):
        client = MagicMock()
        client.get_profile = AsyncMock(
            return_value=Profile(
                profile_id=1,
                display_name="Forælder",
                children=[
                    self._child(1, "280001"),
                    self._child(2, "280001"),
                    self._child(3, "280002"),
                ],
            )
        )
        client.get_common_files = AsyncMock(
            return_value=[
                CommonFile(
                    id=501,
                    title="Ordensregler",
                    created_at="2026-08-01T08:00:00+00:00",
                    institution_name="Eksempel Skole",
                    file_name="ordensregler.pdf",
                    file_url="https://example.com/1",
                )
            ]
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    @pytest.fixture
    def run(self, fake_client, monkeypatch):
        monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=fake_client))

        def invoke(output_format="text"):
            return CliRunner().invoke(
                cli.documents, ["--common"], obj={"OUTPUT_FORMAT": output_format}
            )

        return invoke

    def test_asks_once_per_school_of_the_children(self, run, fake_client):
        run()

        fake_client.get_common_files.assert_awaited_once_with(["280001", "280002"])

    def test_lists_title_school_and_file(self, run):
        result = run()

        assert result.exit_code == 0
        assert "Ordensregler" in result.output
        assert "Eksempel Skole" in result.output
        assert "ordensregler.pdf" in result.output

    def test_json_output_carries_the_download_url(self, run):
        result = run(output_format="json")

        assert json.loads(result.stdout)[0]["file_url"] == "https://example.com/1"


class TestSecureDocuments:
    def test_filters_on_the_users_own_profiles_only(self, monkeypatch):
        """Aula refuses the request when a child's institution profile is in the filter."""
        client = MagicMock()
        client.get_profile = AsyncMock(
            return_value=Profile(
                profile_id=1,
                display_name="Forælder",
                institution_profile_ids=[10, 1, 2],
                _raw={"institutionProfiles": [{"id": 10, "institutionCode": "280001"}]},
            )
        )
        client.get_secure_documents = AsyncMock(return_value=[])
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=client))

        result = CliRunner().invoke(cli.documents, [], obj={"OUTPUT_FORMAT": "text"})

        assert result.exit_code == 0
        client.get_secure_documents.assert_awaited_once_with([10])
