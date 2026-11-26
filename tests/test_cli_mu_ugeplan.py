"""Weekly letters must remain available at schools exposing only MU SSO."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from click.testing import CliRunner

from aula.cli._helpers import _WIDGET_ID_CACHE
from aula.cli.weekly_summary import weekly_summary
from aula.cli.widgets import mu_ugeplan
from aula.http import HttpRequestError
from aula.models import Child, Profile
from aula.models.mu_weekly_letter import MUWeeklyPerson
from tests.cli_support import patch_get_client


@pytest.fixture
def client(monkeypatch):
    _WIDGET_ID_CACHE.clear()
    child = Child.from_dict(
        {
            "id": 101,
            "profileId": 201,
            "name": "Student",
            "userId": "student-login",
            "institutionProfile": {"institutionCode": "school-1"},
        }
    )
    person = MUWeeklyPerson.from_dict(
        {
            "id": 201,
            "navn": "Student",
            "institutioner": [
                {
                    "navn": "School",
                    "ugebreve": [
                        {
                            "tilknytningNavn": "4A",
                            "indhold": "<p>Bring your library book.</p>",
                            "uge": 43,
                        }
                    ],
                }
            ],
        }
    )
    fake = MagicMock()
    fake.get_profile = AsyncMock(
        return_value=Profile(profile_id=1, display_name="Guardian", children=[child])
    )
    fake.get_profile_context = AsyncMock(return_value={"data": {"userId": "guardian-login"}})
    fake.get_widgets = AsyncMock()
    fake.get_calendar_events = AsyncMock(return_value=[])
    fake.get_message_threads = AsyncMock(return_value=[])
    fake.widgets.get_ugeplan = AsyncMock(return_value=[person])
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    patch_get_client(monkeypatch, AsyncMock(return_value=fake))
    yield fake
    _WIDGET_ID_CACHE.clear()


def _invoke(command, output_format):
    args = ["--week", "2026-W43"]
    if command is weekly_summary:
        args += ["--provider", "mu_ugeplan"]
    return CliRunner().invoke(command, args, obj={"OUTPUT_FORMAT": output_format})


@pytest.mark.parametrize("command", [mu_ugeplan, weekly_summary])
@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize(
    ("widget_ids", "expected"),
    [(["0023"], "0023"), (["0023", "0029"], "0029"), (["0029"], "0029")],
)
def test_weekly_letters_use_the_available_widget(
    client, command, output_format, widget_ids, expected
):
    client.get_widgets.return_value = [MagicMock(widget_id=wid) for wid in widget_ids]

    result = _invoke(command, output_format)

    assert result.exit_code == 0, result.output
    client.widgets.get_ugeplan.assert_awaited_once_with(
        expected, ["student-login"], ["school-1"], "2026-W43", "guardian-login"
    )
    if output_format == "json":
        payload = json.loads(result.output)
        people = payload["mu_ugeplan"] if command is weekly_summary else payload
        assert people[0]["institutions"][0]["letters"][0]["content_html"] == (
            "<p>Bring your library book.</p>"
        )
    else:
        assert "Bring your library book." in result.output


@pytest.mark.parametrize("command", [mu_ugeplan, weekly_summary])
def test_no_mu_widget_skips_the_provider(client, command):
    client.get_widgets.return_value = [MagicMock(widget_id="0128")]

    result = _invoke(command, "text")

    assert result.exit_code == 0, result.output
    client.widgets.get_ugeplan.assert_not_awaited()
    if command is mu_ugeplan:
        assert "0029, 0023" in result.output
        assert "aula widgets" in result.output


@pytest.mark.parametrize("command", [mu_ugeplan, weekly_summary])
def test_unreadable_widget_list_still_attempts_the_preferred_widget(client, command):
    client.get_widgets.side_effect = HttpRequestError("Widget lookup failed", 500)

    result = _invoke(command, "text")

    assert result.exit_code == 0, result.output
    client.widgets.get_ugeplan.assert_awaited_once_with(
        "0029", ["student-login"], ["school-1"], "2026-W43", "guardian-login"
    )
