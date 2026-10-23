"""Exhaustive CLI consumers expose partial results in text and JSON."""

import json
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from aula.cli import download_images, messages
from aula.models import Profile
from aula.models.pagination import PaginationResult


def client_for_cli(monkeypatch):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get_profile.return_value = Profile(
        profile_id=1, display_name="Tester", children=[], institution_profile_ids=[1]
    )
    monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=client))
    return client


@pytest.mark.parametrize("output", ["text", "json"])
@pytest.mark.parametrize("complete", [False, True])
def test_search_exposes_completeness(monkeypatch, output, complete):
    client = client_for_cli(monkeypatch)
    reason = "exhausted" if complete else "no_progress"
    client.search_messages_result.return_value = PaginationResult([], complete, reason)
    result = CliRunner().invoke(messages, ["--search", "hello"], obj={"OUTPUT_FORMAT": output})
    assert result.exit_code == (0 if complete else 1), result.output
    if output == "json":
        assert json.loads(result.output) == {
            "items": [],
            "complete": complete,
            "termination_reason": reason,
        }
    elif not complete:
        assert "Incomplete message search: no_progress" in result.output


@pytest.mark.parametrize("output", ["text", "json"])
def test_image_export_surfaces_incomplete_search(monkeypatch, output, tmp_path):
    client = client_for_cli(monkeypatch)
    client.search_messages_result.return_value = PaginationResult([], False, "max_pages")
    result = CliRunner().invoke(
        download_images,
        ["--source", "messages", "--since", "2026-01-01", "--output", str(tmp_path)],
        obj={"OUTPUT_FORMAT": output},
    )
    assert result.exit_code == 1, result.output
    if output == "json":
        report = json.loads(result.output)
        assert report["message_export"] == {"complete": False, "issues": ["search:max_pages"]}
    else:
        assert "Incomplete message export: search:max_pages" in result.output


def test_search_sends_only_the_childrens_profile_ids_and_shows_each_hit(monkeypatch):
    from aula.models import Child
    from aula.models.message import Message

    client = client_for_cli(monkeypatch)
    child = Child(
        id=22, profile_id=7, name="Child One", institution_name="School", profile_picture=""
    )
    client.get_profile.return_value = Profile(
        profile_id=1,
        display_name="Tester",
        children=[child],
        institution_profile_ids=[11, 22],
    )
    hit = {
        "thread": {"id": "1001", "subject": "Pickup"},
        "searchMessage": {
            "id": "m-1",
            "text": {"html": "Teacher: Hello parents"},
            "sendDateTime": "2026-01-05T09:00:00+00:00",
        },
    }
    client.search_messages_result.return_value = PaginationResult(
        [Message.from_search_hit(hit)], True, "exhausted"
    )

    text = CliRunner().invoke(messages, ["--search", "hello"], obj={"OUTPUT_FORMAT": "text"})
    assert text.exit_code == 0, text.output
    ids = client.search_messages_result.call_args.kwargs["institution_profile_ids"]
    assert ids == [22]
    assert "Pickup" in text.output
    assert "Teacher" in text.output
    assert "2026-01-05" in text.output
    assert "Hello parents" in text.output

    out = CliRunner().invoke(messages, ["--search", "hello"], obj={"OUTPUT_FORMAT": "json"})
    item = json.loads(out.output)["items"][0]
    assert item["thread_id"] == "1001"
    assert item["subject"] == "Pickup"
    assert item["sender_name"] == "Teacher"
