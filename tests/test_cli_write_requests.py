"""Each command that writes to Aula sends exactly the request the portal sends.

The reads a command makes first are stubbed. The write goes through the real
``AulaApiClient`` to a ``FakeHttpClient``, so the request body is checked as sent.
"""

import datetime
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from aula.api_client import AulaApiClient
from aula.cli.absence import register_absence, report_sick
from aula.cli.messages import mark_read
from aula.cli.presence import update_presence
from aula.http import HttpResponse
from aula.models import Child, Profile
from aula.models.pickup_responsible import ChildPickupResponsibles
from aula.models.presence_template import PresenceWeekTemplate
from tests.cli_support import patch_get_client
from tests.fakes import FakeHttpClient

OK = HttpResponse(status_code=200, data={"status": {"code": 0}, "data": True})


def _child(child_id: int, name: str) -> Child:
    return Child(
        id=child_id,
        profile_id=child_id + 1000,
        name=name,
        institution_name="Test Institution",
        profile_picture="",
    )


@pytest.fixture
def http():
    return FakeHttpClient()


@pytest.fixture
def client(http, monkeypatch):
    """A real client whose reads are stubbed: two children and no presence restrictions."""
    client = AulaApiClient(http_client=http)
    client.get_profile = AsyncMock(
        return_value=Profile(
            profile_id=1,
            display_name="Værge Et",
            children=[_child(201, "Barn Et"), _child(202, "Barn To")],
        )
    )
    client.get_presence_configuration = AsyncMock(return_value=[])
    client.get_daily_overview = AsyncMock(return_value=None)
    patch_get_client(monkeypatch, AsyncMock(return_value=client))
    return client


def _invoke(command, *args, input=None):
    return CliRunner().invoke(command, list(args), obj={"OUTPUT_FORMAT": "text"}, input=input)


def _posts(http, client, method):
    return http.requests_to(f"{client.api_url}?method={method}")


class TestReportSick:
    METHOD = "presence.updateStatusByInstitutionProfileIds"

    @pytest.mark.parametrize(
        ("flags", "status"),
        [((), 1), (("--undo",), 0), (("--undo", "--present"), 3)],
        ids=["sick", "undo", "undo-present"],
    )
    def test_sends_the_status_for_every_child(self, http, client, flags, status):
        http.route(f"{client.api_url}?method={self.METHOD}", OK)

        result = _invoke(report_sick, *flags, "-y")

        assert result.exit_code == 0, result.output
        [request] = _posts(http, client, self.METHOD)
        assert request.method == "post"
        assert request.json == {"institutionProfileIds": [201, 202], "status": status}

    def test_sends_only_the_chosen_child(self, http, client):
        http.route(f"{client.api_url}?method={self.METHOD}", OK)

        _invoke(report_sick, "--child", "202", "-y")

        [request] = _posts(http, client, self.METHOD)
        assert request.json == {"institutionProfileIds": [202], "status": 1}

    def test_sends_nothing_when_declined(self, http, client):
        result = _invoke(report_sick, input="n\n")

        assert "Cancelled." in result.output
        assert http.requests == []


class TestRegisterAbsence:
    METHOD = "calendar.addVacation"
    TODAY = datetime.date(2026, 11, 11)

    @pytest.fixture(autouse=True)
    def fixed_today(self, monkeypatch):
        monkeypatch.setattr("aula.cli.absence.aula_today", lambda: self.TODAY)
        monkeypatch.setattr("aula.api_client.aula_today", lambda: self.TODAY)

    def test_sends_the_children_dates_and_comment(self, http, client):
        http.route(f"{client.api_url}?method={self.METHOD}", OK)

        result = _invoke(
            register_absence,
            "--from",
            "2026-11-16",
            "--to",
            "2026-11-20",
            "--comment",
            "Ferie",
            "-y",
        )

        assert result.exit_code == 0, result.output
        [request] = _posts(http, client, self.METHOD)
        assert request.method == "post"
        assert request.json == {
            "childIds": [201, 202],
            "intervals": [{"startDate": "2026-11-16", "endDate": "2026-11-20"}],
            "comment": "Ferie",
        }

    def test_sends_one_day_for_one_child_without_a_comment(self, http, client):
        http.route(f"{client.api_url}?method={self.METHOD}", OK)

        _invoke(
            register_absence, "--child", "201", "--from", "2026-11-16", "--to", "2026-11-16", "-y"
        )

        [request] = _posts(http, client, self.METHOD)
        assert request.json == {
            "childIds": [201],
            "intervals": [{"startDate": "2026-11-16", "endDate": "2026-11-16"}],
            "comment": "",
        }

    def test_sends_nothing_when_declined(self, http, client):
        result = _invoke(
            register_absence, "--from", "2026-11-16", "--to", "2026-11-20", input="n\n"
        )

        assert "Cancelled." in result.output
        assert http.requests == []


class TestMarkRead:
    SET = "messaging.setLastReadMessage"

    @staticmethod
    def _page(last_read: str) -> HttpResponse:
        data = {
            "mailBoxOwner": {"mailBoxOwnerType": "institutionProfile", "id": 1},
            "messages": [
                {"id": "m2", "messageType": "Message"},
                {"id": "m1", "messageType": "Message"},
            ],
            "moreMessagesExist": False,
            "lastReadMessageId": last_read,
        }
        return HttpResponse(status_code=200, data={"status": {"code": 0}, "data": data})

    def test_moves_the_read_marker_to_the_newest_message(self, http, client):
        http.route(
            f"{client.api_url}?method=messaging.getMessagesForThread",
            self._page("m1"),
            self._page("m2"),
        )
        http.route(f"{client.api_url}?method={self.SET}", OK)

        result = _invoke(mark_read, "100001")

        assert result.exit_code == 0, result.output
        [request] = _posts(http, client, self.SET)
        assert request.method == "post"
        assert request.json == {
            "threadId": "100001",
            "messageId": "m2",
            "commonInboxId": None,
            "otpInboxId": None,
        }


class TestUpdatePresence:
    METHOD = "presence.updatePresenceTemplate"

    @pytest.fixture
    def presence_client(self, http, client):
        client.get_pickup_responsibles = AsyncMock(
            return_value=[
                ChildPickupResponsibles.from_dict(
                    {
                        "uniStudentId": 201,
                        "relatedPersons": [{"name": "Værge Et", "relation": "Far"}],
                    }
                )
            ]
        )
        client.get_presence_templates = AsyncMock(return_value=[])
        http.route(f"{client.api_url}?method={self.METHOD}", OK)
        return client

    def test_sends_a_new_template_for_every_child(self, http, presence_client):
        result = _invoke(
            update_presence,
            "--date",
            "2026-12-01",
            "--entry-time",
            "08:00",
            "--exit-time",
            "15:00",
            "--exit-with",
            "1",
            "-y",
        )

        assert result.exit_code == 0, result.output
        requests = _posts(http, presence_client, self.METHOD)
        assert [r.method for r in requests] == ["post", "post"]
        assert [r.json for r in requests] == [
            {
                "institutionProfileId": child_id,
                "byDate": "2026-12-01",
                "presenceActivity": {
                    "activityType": 0,
                    "pickup": {
                        "entryTime": "08:00",
                        "exitTime": "15:00",
                        "exitWith": "Værge Et (Far)",
                    },
                },
                "comment": "",
                "repeatPattern": "never",
                "expiresAt": "2027-06-30T00:00:00+00:00",
            }
            for child_id in (201, 202)
        ]

    def test_updates_the_existing_template_and_keeps_what_is_not_given(self, http, presence_client):
        presence_client.get_presence_templates = AsyncMock(
            return_value=[
                PresenceWeekTemplate.from_dict(
                    {
                        "institutionProfile": {"id": 201},
                        "dayTemplates": [
                            {
                                "id": 555,
                                "byDate": "2026-12-01T00:00:00",
                                "entryTime": "07:45",
                                "exitTime": "16:00",
                                "exitWith": "Værge Et (Far)",
                            }
                        ],
                    }
                )
            ]
        )

        result = _invoke(
            update_presence,
            "--child",
            "201",
            "--date",
            "2026-12-01",
            "--exit-time",
            "14:00",
            "--comment",
            "Svømning",
            "--repeat",
            "Weekly",
            "-y",
        )

        assert result.exit_code == 0, result.output
        [request] = _posts(http, presence_client, self.METHOD)
        assert request.json == {
            "institutionProfileId": 201,
            "byDate": "2026-12-01",
            "presenceActivity": {
                "activityType": 0,
                "pickup": {"entryTime": "07:45", "exitTime": "14:00", "exitWith": "Værge Et (Far)"},
            },
            "comment": "Svømning",
            "repeatPattern": "weekly",
            "expiresAt": "2027-06-30T00:00:00+00:00",
            "id": 555,
        }

    def test_sends_nothing_when_declined(self, http, presence_client):
        result = _invoke(
            update_presence, "--date", "2026-12-01", "--exit-time", "15:00", input="0\nn\n"
        )

        assert "Cancelled." in result.output
        assert _posts(http, presence_client, self.METHOD) == []

    @staticmethod
    def _saved_day(client, **day):
        client.get_presence_templates = AsyncMock(
            return_value=[
                PresenceWeekTemplate.from_dict(
                    {
                        "institutionProfile": {"id": 201},
                        "dayTemplates": [{"id": 555, "byDate": "2026-12-01T00:00:00", **day}],
                    }
                )
            ]
        )

    def _send(self, http, client, *args):
        result = _invoke(update_presence, "--child", "201", "--date", "2026-12-01", *args, "-y")
        assert result.exit_code == 0, result.output
        [request] = _posts(http, client, self.METHOD)
        return request.json

    def test_keeps_the_saved_comment_when_none_is_given(self, http, presence_client):
        self._saved_day(presence_client, entryTime="08:00", exitTime="16:00", comment="Svømning")

        sent = self._send(http, presence_client, "--exit-time", "14:00")

        assert sent["comment"] == "Svømning"

    def test_an_empty_comment_clears_the_saved_one(self, http, presence_client):
        self._saved_day(presence_client, entryTime="08:00", exitTime="16:00", comment="Svømning")

        sent = self._send(http, presence_client, "--exit-time", "14:00", "--comment", "")

        assert sent["comment"] == ""

    def test_a_child_who_goes_home_alone_still_does(self, http, presence_client):
        self._saved_day(
            presence_client,
            activityType=1,
            entryTime="08:00",
            selfDeciderStartTime="14:00",
            selfDeciderEndTime="15:30",
        )

        sent = self._send(http, presence_client, "--entry-time", "08:30")

        assert sent["presenceActivity"] == {
            "activityType": 1,
            "selfDecider": {"entryTime": "08:30", "exitStartTime": "14:00", "exitEndTime": "15:30"},
        }

    def test_a_later_start_than_the_window_end_closes_the_window(self, http, presence_client):
        self._saved_day(
            presence_client,
            activityType=1,
            entryTime="08:00",
            selfDeciderStartTime="14:00",
            selfDeciderEndTime="15:30",
        )

        sent = self._send(http, presence_client, "--exit-time", "16:00")

        assert sent["presenceActivity"]["selfDecider"] == {
            "entryTime": "08:00",
            "exitStartTime": "16:00",
            "exitEndTime": "16:00",
        }

    def test_naming_a_pickup_person_means_the_child_is_picked_up(self, http, presence_client):
        self._saved_day(
            presence_client,
            activityType=1,
            entryTime="08:00",
            selfDeciderStartTime="14:00",
            selfDeciderEndTime="15:30",
        )

        sent = self._send(http, presence_client, "--exit-with", "1")

        assert sent["presenceActivity"] == {
            "activityType": 0,
            "pickup": {"entryTime": "08:00", "exitTime": "14:00", "exitWith": "Værge Et (Far)"},
        }

    def test_a_child_who_goes_home_with_someone_keeps_that(self, http, presence_client):
        self._saved_day(
            presence_client, activityType=3, entryTime="08:00", exitTime="15:00", exitWith="Ven"
        )

        sent = self._send(http, presence_client, "--exit-time", "14:00")

        assert sent["presenceActivity"] == {
            "activityType": 3,
            "goHomeWith": {"entryTime": "08:00", "exitTime": "14:00", "exitWith": "Ven"},
        }
