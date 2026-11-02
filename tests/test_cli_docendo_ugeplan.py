"""Docendo returns one plan per class, which the CLI pairs with children by class."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from click.testing import CliRunner

from aula.cli import _WIDGET_ID_CACHE, docendo_ugeplan, weekly_summary
from aula.models import Child, DocendoWeekPlan, Profile


def _child(child_id, name, class_name):
    return Child.from_dict(
        {
            "id": child_id,
            "profileId": child_id + 100,
            "name": name,
            "userId": f"login-{child_id}",
            "institutionProfile": {"institutionCode": "school-1", "metadata": class_name},
        }
    )


def _plan(name, description):
    return DocendoWeekPlan.from_dict(
        {
            "name": name,
            "note": "",
            "events": [
                {
                    "startTime": "2026-10-26T07:00:00Z",
                    "endTime": "2026-10-26T08:30:00Z",
                    "title": "Dansk",
                    "description": f"<p>{description}</p>",
                    "notesForStudents": "<p>Husk bøger</p>",
                },
                {
                    "startTime": "2026-10-26T08:30:00Z",
                    "endTime": "2026-10-26T08:45:00Z",
                    "title": "Fællespause",
                },
            ],
        }
    )


@pytest.fixture
def client(monkeypatch):
    _WIDGET_ID_CACHE.clear()
    fake = MagicMock()
    fake.get_profile = AsyncMock(
        return_value=Profile(
            profile_id=1,
            display_name="Guardian",
            children=[_child(1, "Alpha", "4.a"), _child(2, "Beta", "0B")],
        )
    )
    fake.get_profile_context = AsyncMock(return_value={"data": {"userId": "guardian-login"}})
    fake.get_widgets = AsyncMock(return_value=[MagicMock(widget_id="0057")])
    fake.get_calendar_events = AsyncMock(return_value=[])
    fake.get_message_threads = AsyncMock(return_value=[])
    fake.widgets.get_docendo_weekplan = AsyncMock(
        return_value=[_plan("4A", "Vi læser højt"), _plan("7C", "Fremmed klasse")]
    )
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=fake))
    yield fake
    _WIDGET_ID_CACHE.clear()


def _invoke(command, output_format="text"):
    args = ["--week", "2026-W44"]
    if command is weekly_summary:
        args += ["--provider", "docendo"]
    return CliRunner().invoke(command, args, obj={"OUTPUT_FORMAT": output_format})


def test_command_pairs_plans_with_children_and_lists_the_rest(client):
    result = _invoke(docendo_ugeplan)

    assert result.exit_code == 0, result.output
    client.widgets.get_docendo_weekplan.assert_awaited_once_with("2026-W44")
    assert "Alpha (4A)" in result.output
    assert "7C (no matching child)" in result.output
    assert "Mandag 26/10" in result.output
    assert "- Dansk 08:00-09:30" in result.output
    assert "Vi læser højt" in result.output
    assert "Elevforberedelse: Husk bøger" in result.output
    assert "Fællespause" not in result.output


def test_command_json_tags_each_plan_with_its_child(client):
    result = _invoke(docendo_ugeplan, "json")

    rows = json.loads(result.output)
    assert [(row["name"], row["child_name"]) for row in rows] == [("4A", "Alpha"), ("7C", None)]


def test_an_only_child_gets_plans_that_match_no_class(client):
    client.get_profile.return_value = Profile(
        profile_id=1, display_name="Guardian", children=[_child(1, "Alpha", "")]
    )

    result = _invoke(docendo_ugeplan, "json")

    rows = json.loads(result.output)
    assert [(row["name"], row["child_name"]) for row in rows] == [
        ("4A", "Alpha"),
        ("7C", "Alpha"),
    ]


def test_weekly_summary_shows_only_matched_plans(client):
    result = _invoke(weekly_summary, "json")

    assert result.exit_code == 0, result.output
    plans = json.loads(result.output)["docendo_weekplan"]
    assert [(plan["name"], plan["child_name"]) for plan in plans] == [("4A", "Alpha")]


def test_missing_widget_skips_docendo(client):
    client.get_widgets.return_value = [MagicMock(widget_id="0004")]

    result = _invoke(docendo_ugeplan)

    assert result.exit_code == 0, result.output
    client.widgets.get_docendo_weekplan.assert_not_awaited()
