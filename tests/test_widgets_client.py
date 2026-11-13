"""Tests for widget provider endpoints."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from aula.api_client import AulaApiClient
from aula.const import (
    CICERO_API,
    DOCENDO_API,
    EASYIQ_API,
    EASYIQ_AUTHENTICATE_PATH,
    EASYIQ_CALENDAR_PATH,
    EASYIQ_CHILDREN_PATH,
    EASYIQ_HOMEWORK_PATH,
    EASYIQ_PORTAL,
    EASYIQ_SWITCHCHILD_PATH,
    MEEBOOK_API,
    MIN_UDDANNELSE_API,
    SYSTEMATIC_API,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_EASYIQ_LEGACY,
    WIDGET_EASYIQ_WEEKPLAN,
    WIDGET_HUSKELISTEN,
    WIDGET_MEEBOOK,
    WIDGET_MIN_UDDANNELSE_TASKS,
    WIDGET_MIN_UDDANNELSE_UGEPLAN,
)
from aula.http import AulaNotFoundError, AulaServerError, HttpResponse
from aula.widgets import EasyIQChildNotInPortal, EasyIQWrongChildSession
from aula.widgets.client import _EasyIQContext
from tests.fakes import FakeHttpClient

EASYIQ_AUTHENTICATE_URL = f"{EASYIQ_PORTAL}{EASYIQ_AUTHENTICATE_PATH}"
EASYIQ_CHILDREN_URL = f"{EASYIQ_PORTAL}{EASYIQ_CHILDREN_PATH}"
EASYIQ_SWITCHCHILD_URL = f"{EASYIQ_PORTAL}{EASYIQ_SWITCHCHILD_PATH}"
EASYIQ_CALENDAR_URL = f"{EASYIQ_PORTAL}{EASYIQ_CALENDAR_PATH}"
EASYIQ_HOMEWORK_URL = f"{EASYIQ_PORTAL}{EASYIQ_HOMEWORK_PATH}"
EASYIQ_WEEKPLANINFO_URL = f"{EASYIQ_API}/weekplaninfo"
MEEBOOK_URL = f"{MEEBOOK_API}/relatedweekplan/all"

WIDGET_TOKEN = "widget-token"
AULA_OK = HttpResponse(200, {"status": {"code": 0}, "data": {}})


def _token(value: str = WIDGET_TOKEN) -> HttpResponse:
    return HttpResponse(200, {"status": {"code": 0}, "data": value})


def _token_prefix(client: AulaApiClient) -> str:
    return f"{client.api_url}?method=aulaToken.getAulaToken"


def _token_url(client: AulaApiClient, widget_id: str) -> str:
    return f"{_token_prefix(client)}&widgetId={widget_id}"


def _aula_client(
    http: FakeHttpClient, *tokens: HttpResponse, on_token_refresh: AsyncMock | None = None
) -> AulaApiClient:
    client = AulaApiClient(http, on_token_refresh=on_token_refresh)
    http.route(client.api_url, AULA_OK)
    http.route(_token_prefix(client), *(tokens or (_token(),)))
    return client


def _sent(http: FakeHttpClient) -> list[tuple[str, str]]:
    return [(request.method, request.url) for request in http.requests]


class _InterleavingHttpClient(FakeHttpClient):
    """Yields before every answer, so concurrent callers really do interleave."""

    async def request(self, method, url, **kwargs):
        await asyncio.sleep(0)
        return await super().request(method, url, **kwargs)


@pytest.fixture
def http():
    return FakeHttpClient()


class TestWidgetsClient:
    @pytest.fixture
    def client(self, http):
        client = _aula_client(http)
        # The EasyIQ portal session has its own tests below; marking it done
        # keeps the request-shape tests free of bootstrap plumbing.
        client.widgets._easyiq_session_ready = True
        return client

    @pytest.fixture
    def unbootstrapped_client(self, http):
        return _aula_client(http)

    @pytest.mark.asyncio
    async def test_get_mu_tasks_uses_token_and_expected_request_shape(self, client, http):
        tasks_url = f"{MIN_UDDANNELSE_API}/opgaveliste"
        http.route(
            tasks_url,
            HttpResponse(200, {"opgaver": [{"id": "task-1", "title": "Task 1"}]}),
        )

        tasks = await client.widgets.get_mu_tasks(
            widget_id=WIDGET_MIN_UDDANNELSE_TASKS,
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert [task.id for task in tasks] == ["task-1"]
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_MIN_UDDANNELSE_TASKS)),
            ("get", tasks_url),
        ]
        [request] = http.requests_to(tasks_url)
        assert request.params == {
            "placement": "narrow",
            "sessionUUID": "session-1",
            "userProfile": "guardian",
            "currentWeekNumber": "2026-W09",
            "isMobileApp": "false",
            "childFilter[]": ["child-1"],
            "institutionFilter[]": ["inst-1"],
        }
        assert request.headers == {
            "Authorization": f"Bearer {WIDGET_TOKEN}",
            "Accept": "application/json",
        }

    @pytest.mark.asyncio
    async def test_get_ugeplan_uses_token_and_expected_request_shape(self, client, http):
        ugeplan_url = f"{MIN_UDDANNELSE_API}/ugebrev"
        http.route(
            ugeplan_url,
            HttpResponse(200, {"personer": [{"id": 1, "navn": "Student", "uniLogin": "student1"}]}),
        )

        persons = await client.widgets.get_ugeplan(
            widget_id=WIDGET_MIN_UDDANNELSE_UGEPLAN,
            child_filter=["child-1", "child-2"],
            institution_filter=["inst-1", "inst-2"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert [person.id for person in persons] == [1]
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_MIN_UDDANNELSE_UGEPLAN)),
            ("get", ugeplan_url),
        ]
        [request] = http.requests_to(ugeplan_url)
        assert request.params == {
            "assuranceLevel": "3",
            "childFilter": "child-1,child-2",
            "currentWeekNumber": "2026-W09",
            "institutionFilter": "inst-1,inst-2",
            "isMobileApp": "false",
            "placement": "narrow",
            "sessionUUID": "session-1",
            "userProfile": "guardian",
        }
        assert request.headers == {
            "Authorization": f"Bearer {WIDGET_TOKEN}",
            "Accept": "application/json",
        }

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_uses_token_and_expected_request_shape(self, client, http):
        http.route(
            EASYIQ_WEEKPLANINFO_URL,
            HttpResponse(
                200,
                {
                    "data": {
                        "appointments": [
                            {
                                "appointmentId": "apt-1",
                                "title": "Math",
                                "start": "2026-02-24 08:00",
                                "end": "2026-02-24 09:00",
                                "description": "<p>Algebra</p>",
                                "itemType": 9,
                                "ownerName": "Ada Teacher",
                                "isAllDay": "true",
                                "isNotice": False,
                            }
                        ]
                    }
                },
            ),
        )

        appointments = await client.widgets.get_easyiq_weekplan(
            week="2026-W09",
            session_uuid="session-1",
            institution_filter=["inst-1", "inst-2"],
            child_id="child-1",
        )

        assert [appointment.appointment_id for appointment in appointments] == ["apt-1"]
        assert appointments[0].start == "2026-02-24 08:00"
        assert appointments[0].end == "2026-02-24 09:00"
        assert appointments[0].description == "<p>Algebra</p>"
        assert appointments[0].item_type == 9
        assert appointments[0].owner_name == "Ada Teacher"
        assert appointments[0].is_all_day is True
        assert appointments[0].is_notice is False
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_WEEKPLAN)),
            ("post", EASYIQ_WEEKPLANINFO_URL),
        ]
        [request] = http.requests_to(EASYIQ_WEEKPLANINFO_URL)
        assert request.headers == {
            "Authorization": f"Bearer {WIDGET_TOKEN}",
            "x-aula-institutionfilter": "inst-1,inst-2",
        }
        assert request.json == {
            "sessionId": "session-1",
            "currentWeekNr": "2026-W09",
            "userProfile": "guardian",
            "institutionFilter": ["inst-1", "inst-2"],
            "childFilter": ["child-1"],
        }

    @pytest.mark.asyncio
    async def test_get_easyiq_homework_reads_the_homework_controller(self, client, http):
        """The calendar controller never returns homework; this one does."""
        http.route(
            EASYIQ_HOMEWORK_URL,
            HttpResponse(
                200,
                [
                    {
                        "ItemType": 4,
                        "Start": "2026-02-28T00:00:00",
                        "Courses": "Dansk",
                        "Activities": "Læselektie",
                        "Description": "<p>Pages 40-55</p>",
                    }
                ],
            ),
        )

        homework = await client.widgets.get_easyiq_homework(
            week="2026-W09",
            session_uuid="guardian-1",
            institution_filter=["inst-1", "inst-2"],
            child_id="child-user-1",
            child_profile_id="4242",
        )

        # PascalCase keys: this controller does not answer in camelCase.
        assert len(homework) == 1
        assert homework[0].title == "Dansk"
        assert homework[0].subject == "Dansk"
        assert homework[0].description == "<p>Pages 40-55</p>"
        assert homework[0].due_date == "2026-02-28T00:00:00"
        assert homework[0].is_completed is False

        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_HOMEWORK)),
            ("get", EASYIQ_HOMEWORK_URL),
        ]
        [request] = http.requests_to(EASYIQ_HOMEWORK_URL)
        assert request.params == {
            "date": "2026-02-23T00:00:00Z",
            "activityFilter": "",
            "loginId": "4242",
        }
        assert request.headers == {
            "Authorization": f"Bearer {WIDGET_TOKEN}",
            "Accept": "application/json",
            "x-institutionfilter": "inst-1,inst-2",
            "x-userprofile": "guardian",
            "x-login": "guardian-1",
            "x-requested-with": "XMLHttpRequest",
            "Referer": f"{EASYIQ_PORTAL}/UgeplanWidget",
            "x-child": "child-user-1",
            "x-childfilter": "child-user-1",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "widget_id",
        [WIDGET_EASYIQ_WEEKPLAN, WIDGET_EASYIQ_LEGACY],
        ids=["dedicated", "legacy"],
    )
    async def test_calendar_bootstrap_uses_the_selected_widget(
        self, unbootstrapped_client, http, widget_id
    ):
        client = unbootstrapped_client
        http.route(
            EASYIQ_AUTHENTICATE_URL,
            HttpResponse(200, None),  # bootstrap
            HttpResponse(200, {"child": "barn0003"}),  # confirmation
        )
        http.route(
            EASYIQ_CHILDREN_URL,
            HttpResponse(200, {"Children": [{"Id": "9001", "Login": "barn0003"}]}),
        )
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}]))

        events = await client.widgets.get_easyiq_calendar_events(
            week="2026-W09",
            institution_filter=["inst-1"],
            child_profile_id="4242",
            child_user_id="barn0003",
            all_child_user_ids=["barn0003"],
            guardian_login="guardian-1",
            widget_id=widget_id,
        )

        assert len(events) == 1
        token_urls = [request.url for request in http.requests_to(_token_prefix(client))]
        assert token_urls == [_token_url(client, widget_id)] * 2

    @pytest.mark.asyncio
    async def test_portal_session_is_established_before_any_controller(
        self, unbootstrapped_client, http
    ):
        """Without AuthenticateAulaUser the portal's controllers all 500."""
        client = unbootstrapped_client
        http.route(
            EASYIQ_AUTHENTICATE_URL,
            HttpResponse(200, None),  # bootstrap
            HttpResponse(200, {"child": "BARN0003"}),  # confirmation
        )
        http.route(
            EASYIQ_CHILDREN_URL,
            HttpResponse(200, {"Children": [{"Id": "9001", "Login": "BARN0003"}]}),
        )
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        http.route(
            EASYIQ_HOMEWORK_URL, HttpResponse(200, [{"ItemType": 4, "CoursesDisplay": "Dansk"}])
        )

        homework = await client.widgets.get_easyiq_homework(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "barn0003",
            child_profile_id="4242",
            all_child_user_ids=["barn0003", "barn0004"],
        )

        assert [hw.subject for hw in homework] == ["Dansk"]
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_HOMEWORK)),
            ("post", EASYIQ_AUTHENTICATE_URL),
            ("get", EASYIQ_CHILDREN_URL),
            ("get", _token_url(client, WIDGET_EASYIQ_HOMEWORK)),
            ("post", EASYIQ_SWITCHCHILD_URL),
            ("post", EASYIQ_AUTHENTICATE_URL),
            ("get", EASYIQ_HOMEWORK_URL),
        ]
        # EasyIQ's own ID is used as loginId, matched on Login not Name, and
        # x-childfilter carries every child while x-child carries this one.
        [read] = http.requests_to(EASYIQ_HOMEWORK_URL)
        assert read.params["loginId"] == "9001"
        assert read.headers["x-child"] == "barn0003"
        assert read.headers["x-childfilter"] == "barn0003,barn0004"

    @pytest.mark.asyncio
    async def test_portal_session_runs_once_across_calls(self, unbootstrapped_client, http):
        client = unbootstrapped_client
        http.route(
            EASYIQ_AUTHENTICATE_URL,
            HttpResponse(200, None),  # bootstrap
            HttpResponse(200, {"child": "barn0003"}),  # every confirmation after it
        )
        http.route(
            EASYIQ_CHILDREN_URL,
            HttpResponse(200, {"Children": [{"Id": "9001", "Login": "barn0003"}]}),
        )
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        http.route(
            EASYIQ_HOMEWORK_URL,
            HttpResponse(200, [{"ItemType": 4, "CoursesDisplay": "Dansk"}]),
            HttpResponse(200, [{"ItemType": 4, "CoursesDisplay": "Matematik"}]),
        )
        kwargs = {
            "child_profile_id": "4242",
            "all_child_user_ids": ["barn0003"],
        }

        await client.widgets.get_easyiq_homework(
            "2026-W09", "guardian-1", ["inst-1"], "barn0003", **kwargs
        )
        homework = await client.widgets.get_easyiq_homework(
            "2026-W10", "guardian-1", ["inst-1"], "barn0003", **kwargs
        )

        assert [hw.subject for hw in homework] == ["Matematik"]
        assert len(http.requests_to(EASYIQ_CHILDREN_URL)) == 1
        assert len(http.requests) == 11

    @pytest.mark.asyncio
    async def test_portal_session_runs_once_under_concurrency(self):
        """Callers reading several children at once share the one bootstrap.

        The ready flag alone does not settle this: every caller sees it unset
        while the first is still awaiting the POST, so each would sign in
        again and the portal would be asked to open a session per child.
        """
        http = _InterleavingHttpClient()
        client = _aula_client(http)
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, None))
        http.route(
            EASYIQ_CHILDREN_URL,
            HttpResponse(200, {"Children": [{"Id": "9001", "Login": "barn0003"}]}),
        )

        await asyncio.gather(
            *(
                client.widgets.ensure_easyiq_session(
                    ["inst-1"],
                    "guardian-1",
                    ["barn0003", "barn0004"],
                    WIDGET_EASYIQ_HOMEWORK,
                )
                for _ in range(4)
            )
        )

        assert len(http.requests_to(EASYIQ_AUTHENTICATE_URL)) == 1
        assert client.widgets.resolve_easyiq_child_id("barn0003") == "9001"

    @pytest.mark.asyncio
    async def test_a_failed_bootstrap_leaves_the_guessing_fallback(
        self, unbootstrapped_client, http
    ):
        """Institutions this flow does not suit must still get the old path."""
        client = unbootstrapped_client
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(404))
        http.route(
            EASYIQ_HOMEWORK_URL, HttpResponse(200, [{"ItemType": 4, "CoursesDisplay": "Dansk"}])
        )

        homework = await client.widgets.get_easyiq_homework(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "barn0003",
            child_profile_id="4242",
            all_child_user_ids=["barn0003"],
        )

        assert [hw.subject for hw in homework] == ["Dansk"]
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_HOMEWORK)),
            ("post", EASYIQ_AUTHENTICATE_URL),
            ("get", _token_url(client, WIDGET_EASYIQ_HOMEWORK)),
            ("get", EASYIQ_HOMEWORK_URL),
        ]
        assert http.requests[-1].params["loginId"] == "4242"

    @pytest.mark.asyncio
    async def test_get_easyiq_homework_keeps_rows_of_an_unfamiliar_item_type(self, client, http):
        """The controller only serves homework, so never report nothing instead."""
        http.route(EASYIQ_HOMEWORK_URL, HttpResponse(200, [{"ItemType": 11, "Courses": "Dansk"}]))

        homework = await client.widgets.get_easyiq_homework(
            week="2026-W09",
            session_uuid="guardian-1",
            institution_filter=["inst-1"],
            child_id="child-user-1",
            child_profile_id="4242",
        )

        assert [hw.subject for hw in homework] == ["Dansk"]

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_does_not_use_the_homework_controller(self, client, http):
        http.route(EASYIQ_WEEKPLANINFO_URL, HttpResponse(200, {"data": {"appointments": []}}))
        http.route(
            EASYIQ_CALENDAR_URL, HttpResponse(200, [{"itemType": 9, "courses": "Matematik"}])
        )

        await client.widgets.get_easyiq_weekplan(
            "2026-W09", "guardian-1", ["inst-1"], "child-user-1", child_profile_id="4242"
        )

        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_WEEKPLAN)),
            ("post", EASYIQ_WEEKPLANINFO_URL),
            ("get", _token_url(client, WIDGET_EASYIQ_WEEKPLAN)),
            ("get", EASYIQ_CALENDAR_URL),
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "envelope",
        [
            {"Events": [{"Id": "event-1", "ItemType": 9}]},
            {"WeekPlan": [{"Id": "event-1", "ItemType": 9}]},
            {"Data": {"Events": [{"Id": "event-1", "ItemType": 9}]}},
        ],
        ids=["events", "week-plan", "nested-mixed-case"],
    )
    async def test_easyiq_calendar_reads_observed_envelope_variants(self, client, http, envelope):
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, envelope))

        events = await client.widgets.get_easyiq_calendar_events(
            week="2026-W09",
            institution_filter=["inst-1"],
            child_profile_id="4242",
            child_user_id="child-user-1",
            all_child_user_ids=["child-user-1"],
            guardian_login="guardian-1",
        )

        assert [event.event_id for event in events] == ["event-1"]

    @pytest.mark.asyncio
    async def test_easyiq_calendar_falls_through_to_the_accepted_identifiers(self, client, http):
        """EasyIQ answers 200-with-nothing for identifiers it does not know."""
        http.route(
            EASYIQ_HOMEWORK_URL,
            HttpResponse(200, []),  # profile login / user child
            HttpResponse(200, [{"itemType": 4, "courses": "Dansk"}]),  # user login
        )

        homework = await client.widgets.get_easyiq_homework(
            week="2026-W09",
            session_uuid="guardian-1",
            institution_filter=["inst-1"],
            child_id="child-user-1",
            child_profile_id="4242",
        )

        assert [hw.subject for hw in homework] == ["Dansk"]
        login_ids = [request.params["loginId"] for request in http.requests_to(EASYIQ_HOMEWORK_URL)]
        assert login_ids == ["4242", "child-user-1"]

    @pytest.mark.asyncio
    async def test_easyiq_calendar_reuses_the_identifiers_that_worked(self, client, http):
        """A second week must not re-probe every identifier combination."""
        http.route(
            EASYIQ_HOMEWORK_URL,
            HttpResponse(200, []),
            HttpResponse(200, [{"itemType": 4, "courses": "Dansk"}]),
            HttpResponse(200, [{"itemType": 4, "courses": "Matematik"}]),
        )
        kwargs = {
            "session_uuid": "guardian-1",
            "institution_filter": ["inst-1"],
            "child_id": "child-user-1",
            "child_profile_id": "4242",
        }

        await client.widgets.get_easyiq_homework(week="2026-W09", **kwargs)
        homework = await client.widgets.get_easyiq_homework(week="2026-W10", **kwargs)

        assert [hw.subject for hw in homework] == ["Matematik"]
        login_ids = [request.params["loginId"] for request in http.requests_to(EASYIQ_HOMEWORK_URL)]
        assert login_ids == ["4242", "child-user-1", "child-user-1"]

    @pytest.mark.asyncio
    async def test_easyiq_calendar_raises_when_every_identifier_is_rejected(self, client, http):
        http.route(EASYIQ_HOMEWORK_URL, HttpResponse(404))

        with pytest.raises(AulaNotFoundError):
            await client.widgets.get_easyiq_homework(
                week="2026-W09",
                session_uuid="guardian-1",
                institution_filter=["inst-1"],
                child_id="child-user-1",
                child_profile_id="4242",
            )

        assert len(http.requests_to(EASYIQ_HOMEWORK_URL)) == 4

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_falls_back_to_the_portal_when_the_api_fails(
        self, client, http
    ):
        http.route(EASYIQ_WEEKPLANINFO_URL, HttpResponse(404))
        http.route(
            EASYIQ_CALENDAR_URL,
            HttpResponse(
                200,
                [
                    {
                        "itemType": 9,
                        "courses": "Matematik",
                        "activitiesDisplay": "6A",
                        "start": "2026-02-24T08:00:00",
                    },
                    {"itemType": 4, "courses": "Dansk"},
                ],
            ),
        )

        appointments = await client.widgets.get_easyiq_weekplan(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "child-user-1",
            child_profile_id="4242",
        )

        # Homework rows in the same response stay out of the weekly plan.
        assert [a.title for a in appointments] == ["Matematik"]
        assert appointments[0].start == "2026-02-24T08:00:00"
        # The class survives the mapping to Appointment.
        assert appointments[0].activities == "6A"
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_WEEKPLAN)),
            ("post", EASYIQ_WEEKPLANINFO_URL),
            ("get", _token_url(client, WIDGET_EASYIQ_WEEKPLAN)),
            ("get", EASYIQ_CALENDAR_URL),
        ]

    @pytest.mark.asyncio
    async def test_easyiq_weekplan_fallback_preserves_notice_metadata(self, client, http):
        http.route(EASYIQ_WEEKPLANINFO_URL, HttpResponse(200, {"data": {"appointments": []}}))
        http.route(
            EASYIQ_CALENDAR_URL,
            HttpResponse(
                200,
                {
                    "Events": [
                        {
                            "Id": "notice-1",
                            "ItemType": 8,
                            "Title": "Sports day",
                            "OwnerName": "Ada Teacher",
                        }
                    ]
                },
            ),
        )

        appointments = await client.widgets.get_easyiq_weekplan(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "child-user-1",
            child_profile_id="4242",
        )

        assert len(appointments) == 1
        assert appointments[0].appointment_id == "notice-1"
        assert appointments[0].title == "Sports day"
        assert appointments[0].owner_name == "Ada Teacher"
        assert appointments[0].is_all_day is True
        assert appointments[0].is_notice is True

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_falls_back_when_the_api_returns_nothing(self, client, http):
        """A 200 with an empty appointment list is the shape issue #45 reported."""
        http.route(EASYIQ_WEEKPLANINFO_URL, HttpResponse(200, {"data": {"appointments": []}}))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"itemType": 8, "courses": "Idræt"}]))

        appointments = await client.widgets.get_easyiq_weekplan(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "child-user-1",
            child_profile_id="4242",
        )

        assert [a.title for a in appointments] == ["Idræt"]

    @pytest.mark.asyncio
    async def test_easyiq_calendar_warns_when_the_body_carries_no_events(
        self, client, http, caplog
    ):
        """A licensing error arrives as 2xx with an error object; silence reads as an empty week."""
        envelope = {"ErrorCode": "1", "ErrorDescription": "No license for this school"}
        http.route(EASYIQ_HOMEWORK_URL, HttpResponse(200, envelope))

        homework = await client.widgets.get_easyiq_homework(
            week="2026-W09",
            session_uuid="guardian-1",
            institution_filter=["inst-1"],
            child_id="child-user-1",
            child_profile_id="4242",
        )

        assert homework == []
        assert "returned no readable data" in caplog.text
        assert "ErrorDescription" in caplog.text
        assert "No license for this school" in caplog.text
        # The context needed to tell which child and week went missing.
        assert "child=child-user-1" in caplog.text
        assert "week=2026-W09" in caplog.text

    @pytest.mark.asyncio
    async def test_easyiq_calendar_stays_quiet_on_a_genuinely_empty_week(
        self, client, http, caplog
    ):
        http.route(EASYIQ_HOMEWORK_URL, HttpResponse(200, {"Data": {"Events": []}}))

        homework = await client.widgets.get_easyiq_homework(
            week="2026-W09",
            session_uuid="guardian-1",
            institution_filter=["inst-1"],
            child_id="child-user-1",
            child_profile_id="4242",
        )

        assert homework == []
        assert "no readable data" not in caplog.text

    @pytest.mark.asyncio
    async def test_easyiq_calendar_truncates_a_long_body(self, client, http, caplog):
        http.route(EASYIQ_HOMEWORK_URL, HttpResponse(200, {"error": "x" * 5000}))

        await client.widgets.get_easyiq_homework(
            week="2026-W09",
            session_uuid="guardian-1",
            institution_filter=["inst-1"],
            child_id="child-user-1",
            child_profile_id="4242",
        )

        assert "..." in caplog.text
        assert len(caplog.text) < 1000

    @pytest.mark.asyncio
    async def test_weekplaninfo_warns_when_the_envelope_is_missing(self, client, http, caplog):
        """weekplaninfo has the same hole: no data key, and the fallback hides why."""
        http.route(
            EASYIQ_WEEKPLANINFO_URL,
            HttpResponse(200, {"ErrorCode": "1", "ErrorDescription": "Not licensed"}),
        )
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"itemType": 8, "courses": "Idræt"}]))

        appointments = await client.widgets.get_easyiq_weekplan(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "child-user-1",
            child_profile_id="4242",
        )

        # The portal fallback still answers; the warning explains the first leg.
        assert [a.title for a in appointments] == ["Idræt"]
        assert "EasyIQ weekplaninfo returned no readable data" in caplog.text
        assert "Not licensed" in caplog.text

    @pytest.mark.asyncio
    async def test_weekplaninfo_stays_quiet_on_an_explicit_null_envelope(
        self, client, http, caplog
    ):
        """A null under "data" is the API saying it has none, not a shape we cannot read."""
        http.route(EASYIQ_WEEKPLANINFO_URL, HttpResponse(200, {"data": None}))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"itemType": 8, "courses": "Idræt"}]))

        appointments = await client.widgets.get_easyiq_weekplan(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "child-user-1",
            child_profile_id="4242",
        )

        assert [a.title for a in appointments] == ["Idræt"]
        assert "no readable data" not in caplog.text

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_raises_when_no_profile_id_to_fall_back_with(
        self, client, http
    ):
        http.route(EASYIQ_WEEKPLANINFO_URL, HttpResponse(404))

        with pytest.raises(AulaNotFoundError):
            await client.widgets.get_easyiq_weekplan(
                "2026-W09", "guardian-1", ["inst-1"], "child-user-1"
            )

    @pytest.mark.asyncio
    async def test_get_meebook_weekplan_uses_token_and_expected_request_shape(self, client, http):
        http.route(
            MEEBOOK_URL,
            HttpResponse(
                200,
                [
                    {
                        "name": "Student",
                        "unilogin": "student1",
                        "weekPlan": [
                            {
                                "date": "2026-02-24",
                                "tasks": [
                                    {
                                        "id": 1,
                                        "type": "task",
                                        "title": "Read",
                                        "content": "Chapter 1",
                                        "pill": "Homework",
                                        "link_text": "Open",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            ),
        )

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W9",
            session_uuid="session-1",
        )

        assert [plan.unilogin for plan in plans] == ["student1"]
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_MEEBOOK)),
            ("get", MEEBOOK_URL),
        ]
        [request] = http.requests_to(MEEBOOK_URL)
        assert request.params == {
            "currentWeekNumber": "2026-W09",
            "userProfile": "guardian",
            "childFilter[]": ["child-1"],
            "institutionFilter[]": ["inst-1"],
        }
        assert request.headers == {
            "Authorization": f"Bearer {WIDGET_TOKEN}",
            "Accept": "application/json",
            "sessionUUID": "session-1",
            "X-Version": "1.0",
        }

    @pytest.mark.asyncio
    async def test_get_docendo_weekplan_sends_widget_token_and_session_uuid(self, client, http):
        # header.payload.signature, where payload is {"sub": "session-1"}
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzZXNzaW9uLTEifQ.sig"
        docendo_url = f"{DOCENDO_API}/weekplan"
        http.route(_token_prefix(client), _token(jwt))
        http.route(
            docendo_url,
            HttpResponse(
                200, {"data": {"weekPlans": [{"name": "4A", "note": "", "events": []}, "junk"]}}
            ),
        )

        plans = await client.widgets.get_docendo_weekplan("2026-W9")

        assert [plan.name for plan in plans] == ["4A"]
        assert _sent(http) == [("get", _token_url(client, "0057")), ("get", docendo_url)]
        [request] = http.requests_to(docendo_url)
        assert request.params == {
            "currentWeekNumber": "2026-W09",
            "userProfile": "guardian",
        }
        assert request.headers == {
            "Accept": "application/json",
            "Authorization": f"Baerer {jwt}",
            "Origin": "https://www.aula.dk",
            "Referer": "https://www.aula.dk/",
            "aulasessionuuid": "session-1",
        }

    @pytest.mark.asyncio
    async def test_get_docendo_weekplan_omits_session_uuid_for_opaque_token(self, client, http):
        docendo_url = f"{DOCENDO_API}/weekplan"
        http.route(_token_prefix(client), _token("opaque"))
        http.route(docendo_url, HttpResponse(200, {"data": {"weekPlans": []}}))

        assert await client.widgets.get_docendo_weekplan("2026-W09") == []
        [request] = http.requests_to(docendo_url)
        assert "aulasessionuuid" not in request.headers

    @pytest.mark.asyncio
    async def test_get_docendo_weekplan_unexpected_shape_is_empty(self, client, http, caplog):
        http.route(f"{DOCENDO_API}/weekplan", HttpResponse(200, {"error": "Klasse 4A ikke fundet"}))

        assert await client.widgets.get_docendo_weekplan("2026-W09") == []
        assert "keys ['error']" in caplog.text
        assert "Klasse 4A" not in caplog.text

    @pytest.mark.asyncio
    async def test_get_momo_courses_uses_token_and_expected_request_shape(self, client, http):
        courses_url = f"{SYSTEMATIC_API}/courses/v1"
        http.route(
            courses_url,
            HttpResponse(
                200,
                [
                    {
                        "userId": "child-1",
                        "name": "Student",
                        "courses": [
                            {
                                "id": "course-1",
                                "title": "Danish",
                                "institutionId": "inst-1",
                                "image": None,
                            }
                        ],
                    }
                ],
            ),
        )

        courses = await client.widgets.get_momo_courses(
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
        )

        assert [course.user_id for course in courses] == ["child-1"]
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_HUSKELISTEN)),
            ("get", courses_url),
        ]
        [request] = http.requests_to(courses_url)
        assert request.params == {
            "widgetVersion": "1.3",
            "userProfile": "guardian",
            "sessionId": "session-1",
            "children": ["child-1"],
            "institutions": ["inst-1"],
        }
        assert request.headers == {
            "Aula-Authorization": f"Bearer {WIDGET_TOKEN}",
        }

    @pytest.mark.asyncio
    async def test_get_momo_reminders_uses_token_and_expected_request_shape(self, client, http):
        reminders_url = f"{SYSTEMATIC_API}/reminders/v1"
        http.route(
            reminders_url,
            HttpResponse(
                200,
                [
                    {
                        "userId": 164625,
                        "userName": "Emilie Efternavn",
                        "courseReminders": [],
                        "assignmentReminders": [
                            {
                                "id": 1,
                                "institutionName": "Holme Skole",
                                "institutionId": 183,
                                "dueDate": "2026-03-01T11:00:00Z",
                                "courseId": 297469,
                                "teamNames": ["5A"],
                                "teamIds": [65271],
                                "courseSubjects": [],
                                "assignmentId": 5027904,
                                "assignmentText": "Skriv en novelle",
                            }
                        ],
                        "teamReminders": [
                            {
                                "id": 76169,
                                "institutionName": "Holme Skole",
                                "institutionId": 183,
                                "dueDate": "2026-02-28T23:00:00Z",
                                "teamId": 65240,
                                "teamName": "2A",
                                "reminderText": "Lektie: Matematikfessor",
                                "createdBy": "Peter",
                                "lastEditBy": "Peter",
                                "subjectName": "Matematik",
                            }
                        ],
                    }
                ],
            ),
        )

        users = await client.widgets.get_momo_reminders(
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
            from_date="2026-02-26",
            due_no_later_than="2026-03-05",
        )

        assert len(users) == 1
        assert users[0].user_name == "Emilie Efternavn"
        assert len(users[0].team_reminders) == 1
        assert users[0].team_reminders[0].subject_name == "Matematik"
        assert len(users[0].assignment_reminders) == 1
        assert users[0].assignment_reminders[0].assignment_text == "Skriv en novelle"

        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_HUSKELISTEN)),
            ("get", reminders_url),
        ]
        [request] = http.requests_to(reminders_url)
        assert request.params == {
            "widgetVersion": "1.10",
            "userProfile": "guardian",
            "sessionId": "session-1",
            "children": ["child-1"],
            "institutions": ["inst-1"],
            "from": "2026-02-26",
            "dueNoLaterThan": "2026-03-05",
        }
        assert request.headers == {
            "Aula-Authorization": f"Bearer {WIDGET_TOKEN}",
        }

    @pytest.mark.asyncio
    async def test_get_library_status_uses_token_and_expected_request_shape(self, client, http):
        library_url = f"{CICERO_API}/library/status/v3"
        http.route(
            library_url,
            HttpResponse(
                200,
                {
                    "loans": [
                        {
                            "id": 1,
                            "title": "Book",
                            "author": "Author",
                            "patronDisplayName": "Student",
                            "dueDate": "2026-03-01",
                            "numberOfLoans": 1,
                        }
                    ],
                    "longtermLoans": [],
                    "reservations": [],
                    "branchIds": ["branch-1"],
                },
            ),
        )

        status = await client.widgets.get_library_status(
            widget_id=WIDGET_HUSKELISTEN,
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
        )

        assert [loan.id for loan in status.loans] == [1]
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_HUSKELISTEN)),
            ("get", library_url),
        ]
        [request] = http.requests_to(library_url)
        assert request.params == {
            "coverImageHeight": "160",
            "widgetVersion": "1.6",
            "userProfile": "guardian",
            "sessionUUID": "session-1",
            "institutions": ["inst-1"],
            "children": ["child-1"],
        }
        assert request.headers == {
            "Authorization": f"Bearer {WIDGET_TOKEN}",
            "Accept": "application/json",
        }


class TestWidgetsClientMalformedResponses:
    """Providers sometimes answer 2xx with an error object instead of an array.

    Meebook returns ``{"message": "JWT-Token expired, please renew."}`` when its
    widget token has expired; iterating that yields the keys as strings.
    """

    JWT_EXPIRED = {"message": "JWT-Token expired, please renew."}

    @pytest.fixture
    def client(self, http):
        return _aula_client(http)

    @pytest.mark.asyncio
    async def test_meebook_weekplan_refreshes_and_retries_on_jwt_expiry(self, http):
        refresh = AsyncMock(return_value="new-access-token")
        client = _aula_client(
            http, _token("token-old"), _token("token-new"), on_token_refresh=refresh
        )
        http.route(
            MEEBOOK_URL,
            HttpResponse(200, self.JWT_EXPIRED),
            HttpResponse(200, [{"name": "Child", "unilogin": "child-1", "weekPlan": []}]),
        )

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert [plan.name for plan in plans] == ["Child"]
        refresh.assert_awaited_once()
        first, second = http.requests_to(MEEBOOK_URL)
        assert first.headers["Authorization"] == "Bearer token-old"
        assert second.headers["Authorization"] == "Bearer token-new"

    @pytest.mark.asyncio
    async def test_meebook_weekplan_returns_empty_when_jwt_refresh_is_unavailable(
        self, http, caplog
    ):
        refresh = AsyncMock(return_value=None)
        client = _aula_client(http, on_token_refresh=refresh)
        http.route(MEEBOOK_URL, HttpResponse(200, self.JWT_EXPIRED))

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert plans == []
        refresh.assert_awaited_once()
        assert len(http.requests_to(_token_prefix(client))) == 1
        assert len(http.requests_to(MEEBOOK_URL)) == 1
        assert "Meebook weekplan JWT expired and could not be renewed" in caplog.text

    @pytest.mark.asyncio
    async def test_meebook_weekplan_retries_only_once_when_jwt_stays_expired(self, http, caplog):
        refresh = AsyncMock(return_value="new-access-token")
        client = _aula_client(
            http, _token("token-old"), _token("token-new"), on_token_refresh=refresh
        )
        http.route(MEEBOOK_URL, HttpResponse(200, self.JWT_EXPIRED))

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert plans == []
        refresh.assert_awaited_once()
        assert len(http.requests_to(_token_prefix(client))) == 2
        assert len(http.requests_to(MEEBOOK_URL)) == 2
        assert "Meebook weekplan JWT expired and could not be renewed" in caplog.text

    @pytest.mark.asyncio
    async def test_meebook_weekplan_does_not_refresh_for_unrelated_error_object(self, http, caplog):
        refresh = AsyncMock(return_value="new-access-token")
        client = _aula_client(http, on_token_refresh=refresh)
        http.route(MEEBOOK_URL, HttpResponse(200, {"message": "Service temporarily unavailable"}))

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert plans == []
        refresh.assert_not_awaited()
        assert "Meebook weekplan returned dict instead of a list" in caplog.text

    @pytest.mark.asyncio
    async def test_meebook_weekplan_skips_non_dict_items(self, client, http, caplog):
        http.route(
            MEEBOOK_URL, HttpResponse(200, [{"name": "Child", "unilogin": "abc123"}, "junk", None])
        )

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert [plan.name for plan in plans] == ["Child"]
        assert "Meebook weekplan returned 2 non-dict item(s)" in caplog.text

    @pytest.mark.asyncio
    async def test_meebook_weekplan_returns_empty_on_unparseable_body(self, client, http):
        # http_httpx sets data to None when the body is not valid JSON.
        http.route(MEEBOOK_URL, HttpResponse(200, None))

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert plans == []

    @pytest.mark.asyncio
    async def test_momo_courses_returns_empty_on_error_object(self, client, http, caplog):
        http.route(f"{SYSTEMATIC_API}/courses/v1", HttpResponse(200, self.JWT_EXPIRED))

        courses = await client.widgets.get_momo_courses(
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
        )

        assert courses == []
        assert "Huskelisten courses returned dict instead of a list" in caplog.text

    @pytest.mark.asyncio
    async def test_momo_reminders_returns_empty_on_error_object(self, client, http, caplog):
        http.route(f"{SYSTEMATIC_API}/reminders/v1", HttpResponse(200, self.JWT_EXPIRED))

        reminders = await client.widgets.get_momo_reminders(
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
            from_date="2026-03-01",
            due_no_later_than="2026-03-31",
        )

        assert reminders == []
        assert "Huskelisten reminders returned dict instead of a list" in caplog.text

    @pytest.mark.asyncio
    async def test_library_status_returns_empty_on_list_body(self, client, http, caplog):
        http.route(f"{CICERO_API}/library/status/v3", HttpResponse(200, ["unexpected"]))

        status = await client.widgets.get_library_status(
            widget_id=WIDGET_HUSKELISTEN,
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
        )

        assert status.loans == []
        assert status.longterm_loans == []
        assert status.reservations == []
        assert status.branch_ids == []
        assert "Library status returned list instead of an object" in caplog.text


class TestEasyiqProtocolCorrectIdentifier:
    """Issue #68: the real client reuses one parent ``loginId`` for every
    child and pairs it with the child's real ``Login`` string, never a
    per-child ``loginId``.
    """

    @pytest.fixture
    def client(self, http):
        return _aula_client(http)

    @pytest.mark.asyncio
    async def test_authenticate_response_populates_the_parent_login_id(self, client, http):
        http.route(
            EASYIQ_AUTHENTICATE_URL,
            HttpResponse(200, {"loginId": "parent-42", "child": "1", "schoolId": "9"}),
        )
        http.route(EASYIQ_CHILDREN_URL, HttpResponse(200, {"Children": []}))

        await client.widgets.ensure_easyiq_session(
            ["inst-1"], "guardian-1", ["barn0003"], WIDGET_EASYIQ_HOMEWORK
        )

        assert client.widgets._easyiq_parent_login_id == "parent-42"

    @pytest.mark.asyncio
    async def test_authenticate_response_missing_login_id_does_not_raise(self, client, http):
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {"loginTypeId": "1"}))
        http.route(EASYIQ_CHILDREN_URL, HttpResponse(200, {"Children": []}))

        await client.widgets.ensure_easyiq_session(
            ["inst-1"], "guardian-1", ["barn0003"], WIDGET_EASYIQ_HOMEWORK
        )

        assert client.widgets._easyiq_parent_login_id is None

    @pytest.mark.asyncio
    async def test_authenticate_response_unparseable_body_does_not_raise(self, client, http):
        # http_httpx sets data to None when the body is not valid JSON.
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, None))
        http.route(EASYIQ_CHILDREN_URL, HttpResponse(200, {"Children": []}))

        await client.widgets.ensure_easyiq_session(
            ["inst-1"], "guardian-1", ["barn0003"], WIDGET_EASYIQ_HOMEWORK
        )

        assert client.widgets._easyiq_parent_login_id is None
        # A bad AuthenticateAulaUser body is not fatal: GetChildren still runs.
        assert len(http.requests_to(EASYIQ_CHILDREN_URL)) == 1

    @pytest.mark.asyncio
    async def test_get_children_stores_the_real_login_string_and_id(self, client, http):
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {}))
        http.route(
            EASYIQ_CHILDREN_URL,
            HttpResponse(200, {"Children": [{"Id": "9001", "Login": "BARN0003"}]}),
        )

        await client.widgets.ensure_easyiq_session(
            ["inst-1"], "guardian-1", ["barn0003"], WIDGET_EASYIQ_HOMEWORK
        )

        assert client.widgets.resolve_easyiq_child_id("barn0003") == "9001"
        # The real casing survives, even though the lookup key is casefolded.
        assert client.widgets.resolve_easyiq_child_login("barn0003") == "BARN0003"

    def test_identifier_variants_lead_with_the_protocol_correct_pair(self, client):
        client.widgets._easyiq_parent_login_id = "parent-42"
        client.widgets._easyiq_child_logins["barn0003"] = "BARN0003"

        variants = client.widgets.easyiq_identifier_variants(
            "4242", "barn0003", "guardian-1", "9001"
        )

        assert variants[0] == ("parent-42", "BARN0003")
        # The rest of the fallback order is unchanged.
        assert variants[1:] == [
            ("9001", "barn0003"),
            ("4242", "barn0003"),
            ("barn0003", "barn0003"),
            ("4242", "4242"),
            ("guardian-1", "barn0003"),
        ]

    def test_identifier_variants_fall_back_unchanged_without_the_protocol_pair(self, client):
        variants = client.widgets.easyiq_identifier_variants(
            "4242", "barn0003", "guardian-1", "9001"
        )

        assert variants == [
            ("9001", "barn0003"),
            ("4242", "barn0003"),
            ("barn0003", "barn0003"),
            ("4242", "4242"),
            ("guardian-1", "barn0003"),
        ]

    def test_identifier_variants_need_both_halves_of_the_protocol_pair(self, client):
        """A parent loginId with no matching real Login is not enough."""
        client.widgets._easyiq_parent_login_id = "parent-42"

        variants = client.widgets.easyiq_identifier_variants("4242", "barn0003", "guardian-1")

        assert ("parent-42", "barn0003") not in variants

    @pytest.mark.asyncio
    async def test_switch_child_posts_the_easyiq_id_as_login_id(self, client, http):
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))

        await client.widgets.switch_easyiq_child(
            "9001",
            _EasyIQContext(
                token="token-switch",
                institution_filter=("inst-1",),
                guardian_login="guardian-1",
                child_user_ids=("barn0003", "barn0004"),
                widget_id=WIDGET_EASYIQ_WEEKPLAN,
                child_user_id="barn0003",
            ),
        )

        [switch] = http.requests
        assert (switch.method, switch.url) == ("post", EASYIQ_SWITCHCHILD_URL)
        # loginId is the Id GetChildren gave for this child -- not its Login,
        # and not Aula's own userId.
        assert switch.params == {"loginId": "9001"}
        assert switch.headers["x-child"] == "barn0003"
        assert switch.headers["Authorization"] == "Bearer token-switch"

    def test_easyiq_headers_come_from_the_context(self, client):
        """Every portal call sends these, so their shape is the protocol."""
        headers = client.widgets.easyiq_headers(
            _EasyIQContext(
                token="token-easy",
                institution_filter=("inst-1", "inst-2"),
                guardian_login="Guardian-1",
                child_user_ids=("barn0001", "barn0002"),
                widget_id=WIDGET_EASYIQ_WEEKPLAN,
                child_user_id="barn0002",
            )
        )

        assert headers == {
            "Authorization": "Bearer token-easy",
            "Accept": "application/json",
            "x-institutionfilter": "inst-1,inst-2",
            "x-userprofile": "guardian",
            "x-login": "Guardian-1",
            "x-child": "barn0002",
            "x-childfilter": "barn0001,barn0002",
            "x-requested-with": "XMLHttpRequest",
            "Referer": f"{EASYIQ_PORTAL}/UgeplanWidget",
        }

    def test_a_context_without_a_selected_child_sends_the_first_child(self, client):
        """The bootstrap selects no child, but the portal needs x-child on every call."""
        context = _EasyIQContext(
            token="token-boot",
            institution_filter=("inst-1",),
            guardian_login="guardian-1",
            child_user_ids=("barn0001", "barn0002"),
            widget_id=WIDGET_EASYIQ_WEEKPLAN,
        )

        assert client.widgets.easyiq_headers(context)["x-child"] == "barn0001"

    @staticmethod
    def _bootstrapped(client, children):
        """Put a client in the state a successful bootstrap leaves it in."""
        client.widgets._easyiq_session_ready = True
        client.widgets._easyiq_parent_login_id = "parent-42"
        for entry in children:
            key = entry["Login"].casefold()
            client.widgets._easyiq_child_ids[key] = entry["Id"]
            client.widgets._easyiq_child_logins[key] = entry["Login"]
        client.widgets._easyiq_children_known = True

    @pytest.mark.asyncio
    async def test_the_week_read_is_preceded_by_switch_child(self, client, http):
        self._bootstrapped(client, [{"Id": "9001", "Login": "barn0003"}])
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {"child": "barn0003"}))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}]))

        events = await client.widgets.get_easyiq_calendar_events(
            week="2026-W09",
            institution_filter=["inst-1"],
            child_profile_id="4242",
            child_user_id="barn0003",
            all_child_user_ids=["barn0003"],
            guardian_login="guardian-1",
        )

        assert len(events) == 1
        # The switch has to happen first: identity headers alone do not move
        # the portal off whichever child the session is already on (#68).
        # Then the switch is confirmed, and only then is the week read. One
        # token, shared by all three.
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_WEEKPLAN)),
            ("post", EASYIQ_SWITCHCHILD_URL),
            ("post", EASYIQ_AUTHENTICATE_URL),
            ("get", EASYIQ_CALENDAR_URL),
        ]
        [switch] = http.requests_to(EASYIQ_SWITCHCHILD_URL)
        assert switch.params == {"loginId": "9001"}

    @pytest.mark.asyncio
    async def test_child_without_an_easyiq_identity_is_not_read_at_all(self, client, http):
        """The daycare case from #68: no identity means no week plan.

        Reading anyway does not fail, it returns whichever child the session
        was last switched to -- wrong data that looks entirely valid.
        """
        self._bootstrapped(client, [{"Id": "9001", "Login": "barn0003"}])

        with pytest.raises(EasyIQChildNotInPortal):
            await client.widgets.get_easyiq_calendar_events(
                week="2026-W09",
                institution_filter=["inst-2"],
                child_profile_id="4343",
                child_user_id="barn0004",  # in daycare, absent from GetChildren
                all_child_user_ids=["barn0003", "barn0004"],
                guardian_login="guardian-1",
            )

        assert http.requests == []

    @pytest.mark.asyncio
    async def test_the_session_is_made_under_every_institution(self, client, http):
        """The bootstrap is cached, so it must not be scoped to one child.

        Callers pass the child's own institution for the read. If that were
        also what the session was made under, whichever child was read first
        would decide which children GetChildren ever lists, and the rest
        would look like children EasyIQ does not know.
        """
        client.widgets._easyiq_session_ready = False
        http.route(
            EASYIQ_AUTHENTICATE_URL,
            HttpResponse(200, {"loginId": "parent-42"}),  # bootstrap
            HttpResponse(200, {"child": "barn0003"}),  # confirmation
        )
        http.route(
            EASYIQ_CHILDREN_URL,
            HttpResponse(200, {"Children": [{"Id": "9001", "Login": "barn0003"}]}),
        )
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}]))

        await client.widgets.get_easyiq_calendar_events(
            week="2026-W09",
            institution_filter=["751052"],  # this child's school
            child_profile_id="4242",
            child_user_id="barn0003",
            all_child_user_ids=["barn0003", "barn0004"],
            guardian_login="guardian-1",
            all_institution_filter=["751052", "751056", "G20365"],
        )

        every = "751052,751056,G20365"
        bootstrap, confirmation = http.requests_to(EASYIQ_AUTHENTICATE_URL)
        [children] = http.requests_to(EASYIQ_CHILDREN_URL)
        [switch] = http.requests_to(EASYIQ_SWITCHCHILD_URL)
        [read] = http.requests_to(EASYIQ_CALENDAR_URL)
        assert bootstrap.headers["x-institutionfilter"] == every
        assert children.headers["x-institutionfilter"] == every
        # Switch, confirmation and read still go out under the child's own institution.
        for step in (switch, confirmation, read):
            assert step.headers["x-institutionfilter"] == "751052"

    @pytest.mark.asyncio
    async def test_the_session_falls_back_to_the_childs_institution(self, client, http):
        """Callers that do not know the full list keep the old behaviour."""
        client.widgets._easyiq_session_ready = False
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {"loginId": "parent-42"}))
        http.route(EASYIQ_CHILDREN_URL, HttpResponse(200, {"Children": []}))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}]))

        await client.widgets.get_easyiq_calendar_events(
            week="2026-W09",
            institution_filter=["751052"],
            child_profile_id="4242",
            child_user_id="barn0003",
            all_child_user_ids=["barn0003"],
            guardian_login="guardian-1",
        )

        [bootstrap] = http.requests_to(EASYIQ_AUTHENTICATE_URL)
        assert bootstrap.headers["x-institutionfilter"] == "751052"

    @pytest.mark.asyncio
    async def test_a_failed_switch_child_surfaces_rather_than_returning_data(self, client, http):
        self._bootstrapped(client, [{"Id": "9001", "Login": "barn0003"}])
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(500))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}]))

        with pytest.raises(AulaServerError):
            await client.widgets.get_easyiq_calendar_events(
                week="2026-W09",
                institution_filter=["inst-1"],
                child_profile_id="4242",
                child_user_id="barn0003",
                all_child_user_ids=["barn0003"],
                guardian_login="guardian-1",
            )

        # The read never happened: a week that could belong to any child is
        # worse than an error the caller can report.
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_WEEKPLAN)),
            ("post", EASYIQ_SWITCHCHILD_URL),
        ]

    @pytest.mark.asyncio
    async def test_switch_and_read_are_not_interleaved_between_children(self):
        """Two children read at once must not have their switches interleave.

        SwitchChild moves server-side session state, so a switch landing
        between another child's switch and read would answer both with the
        same week.
        """
        http = _InterleavingHttpClient()
        client = _aula_client(http)
        self._bootstrapped(
            client,
            [{"Id": "9001", "Login": "barn0003"}, {"Id": "9002", "Login": "barn0004"}],
        )
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        # A confirmation that names no child lets either child go first.
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {}))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}]))

        async def _read(child_user_id, child_profile_id):
            return await client.widgets.get_easyiq_calendar_events(
                week="2026-W09",
                institution_filter=["inst-1"],
                child_profile_id=child_profile_id,
                child_user_id=child_user_id,
                all_child_user_ids=["barn0003", "barn0004"],
                guardian_login="guardian-1",
            )

        await asyncio.gather(_read("barn0003", "4242"), _read("barn0004", "4343"))

        sequence = [
            f"switch:{request.params['loginId']}"
            if request.url == EASYIQ_SWITCHCHILD_URL
            else f"read:{request.headers['x-child']}"
            for request in http.requests
            if request.url in (EASYIQ_SWITCHCHILD_URL, EASYIQ_CALENDAR_URL)
        ]
        pairs = [tuple(sequence[i : i + 2]) for i in range(0, len(sequence), 2)]
        assert sorted(pairs) == [
            ("switch:9001", "read:barn0003"),
            ("switch:9002", "read:barn0004"),
        ]

    @pytest.mark.asyncio
    async def test_concurrent_reads_keep_their_own_child_and_institution(self):
        """A sibling read in flight must not change who this read's requests are for."""
        http = _InterleavingHttpClient()
        client = _aula_client(http)
        self._bootstrapped(
            client,
            [{"Id": "9001", "Login": "barn0001"}, {"Id": "9002", "Login": "barn0002"}],
        )
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        # A confirmation that names no child lets either child go first.
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {}))
        http.route(
            EASYIQ_CALENDAR_URL,
            HttpResponse(200, [{"ItemType": 9, "Title": "first-answer"}]),
            HttpResponse(200, [{"ItemType": 9, "Title": "second-answer"}]),
        )

        async def _read(child_user_id, child_profile_id, institution):
            return await client.widgets.get_easyiq_calendar_events(
                week="2026-W09",
                institution_filter=[institution],
                child_profile_id=child_profile_id,
                child_user_id=child_user_id,
                all_child_user_ids=["barn0001", "barn0002"],
                guardian_login="guardian-1",
            )

        first, second = await asyncio.gather(
            _read("barn0001", "4242", "SKOLE-1"),
            _read("barn0002", "4343", "SKOLE-2"),
        )

        # Each caller gets the answer to the read that carried its own child.
        reads = http.requests_to(EASYIQ_CALENDAR_URL)
        answered = dict(
            zip(
                (read.headers["x-child"] for read in reads),
                ("first-answer", "second-answer"),
                strict=True,
            )
        )
        assert [event.title for event in first] == [answered["barn0001"]]
        assert [event.title for event in second] == [answered["barn0002"]]

        step = {
            EASYIQ_SWITCHCHILD_URL: "switch",
            EASYIQ_AUTHENTICATE_URL: "confirm",
            EASYIQ_CALENDAR_URL: "read",
        }
        seen = [
            (step[request.url], request.headers["x-child"], request.headers["x-institutionfilter"])
            for request in http.requests_to(EASYIQ_PORTAL)
        ]
        steps = sorted(tuple(seen[i : i + 3]) for i in range(0, len(seen), 3))
        assert steps == [
            tuple((step, "barn0001", "SKOLE-1") for step in ("switch", "confirm", "read")),
            tuple((step, "barn0002", "SKOLE-2") for step in ("switch", "confirm", "read")),
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reader", ["get_easyiq_calendar_events", "get_easyiq_homework_events"])
    @pytest.mark.parametrize(
        ("authenticate", "children"),
        [
            (HttpResponse(500), None),
            (HttpResponse(200, {}), HttpResponse(500)),
            (HttpResponse(200, {}), HttpResponse(200, {"Children": []})),
            (HttpResponse(200, {}), HttpResponse(200, {"Children": [{"Name": "Child"}]})),
        ],
        ids=["authentication-failed", "children-failed", "empty-children", "unidentified-children"],
    )
    async def test_unidentified_children_refuse_multi_child_reads(
        self, client, http, reader, authenticate, children
    ):
        http.route(EASYIQ_AUTHENTICATE_URL, authenticate)
        if children is not None:
            http.route(EASYIQ_CHILDREN_URL, children)
        sibling_lesson = HttpResponse(200, [{"ItemType": 9, "Title": "Sibling's lesson"}])
        http.route(EASYIQ_CALENDAR_URL, sibling_lesson)
        http.route(EASYIQ_HOMEWORK_URL, sibling_lesson)

        with pytest.raises(RuntimeError, match="portal did not identify the children"):
            await getattr(client.widgets, reader)(
                week="2026-W09",
                institution_filter=["inst-1"],
                child_profile_id="4242",
                child_user_id="barn0003",
                all_child_user_ids=["barn0003", "barn0004"],
                guardian_login="guardian-1",
            )

        assert http.requests_to(EASYIQ_CALENDAR_URL) == []
        assert http.requests_to(EASYIQ_HOMEWORK_URL) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reader", ["get_easyiq_calendar_events", "get_easyiq_homework_events"])
    async def test_failed_bootstrap_preserves_single_child_reads(self, client, http, reader):
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(500))
        lesson = HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}])
        http.route(EASYIQ_CALENDAR_URL, lesson)
        http.route(EASYIQ_HOMEWORK_URL, lesson)

        events = await getattr(client.widgets, reader)(
            week="2026-W09",
            institution_filter=["inst-1"],
            child_profile_id="4242",
            child_user_id="barn0003",
            all_child_user_ids=["barn0003"],
            guardian_login="guardian-1",
        )

        assert [event.title for event in events] == ["Dansk"]

    @pytest.mark.asyncio
    async def test_no_switch_when_the_bootstrap_resolved_no_children(self, client, http):
        """Institutions the bootstrap does not suit keep the old guessing path."""
        client.widgets._easyiq_session_ready = True  # bootstrap ran, found nothing
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}]))

        events = await client.widgets.get_easyiq_calendar_events(
            week="2026-W09",
            institution_filter=["inst-1"],
            child_profile_id="4242",
            child_user_id="barn0003",
            all_child_user_ids=["barn0003"],
            guardian_login="guardian-1",
        )

        assert len(events) == 1
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_WEEKPLAN)),
            ("get", EASYIQ_CALENDAR_URL),
        ]

    @pytest.mark.asyncio
    async def test_a_switch_that_did_not_take_effect_is_refused(self, client, http):
        """SwitchChild answering 200 is not proof the session moved.

        Two other Aula clients guess identifiers and treat "200 and
        parseable" as success, which is exactly how another child's week
        gets shipped as if it were this child's.
        """
        self._bootstrapped(client, [{"Id": "9001", "Login": "barn0003"}])
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))  # SwitchChild says 200
        # but it is on the sibling
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {"child": "barn0004"}))
        http.route(
            EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Wrong child"}])
        )

        with pytest.raises(EasyIQWrongChildSession):
            await client.widgets.get_easyiq_calendar_events(
                week="2026-W09",
                institution_filter=["inst-1"],
                child_profile_id="4242",
                child_user_id="barn0003",
                all_child_user_ids=["barn0003", "barn0004"],
                guardian_login="guardian-1",
            )

        # Refused before the read, so no wrong-child data is ever parsed.
        assert _sent(http) == [
            ("get", _token_url(client, WIDGET_EASYIQ_WEEKPLAN)),
            ("post", EASYIQ_SWITCHCHILD_URL),
            ("post", EASYIQ_AUTHENTICATE_URL),
        ]

    @pytest.mark.asyncio
    async def test_the_confirmation_ignores_casing(self, client, http):
        self._bootstrapped(client, [{"Id": "9001", "Login": "BARN0003"}])
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        # Same child, other casing.
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {"child": "barn0003"}))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}]))

        events = await client.widgets.get_easyiq_calendar_events(
            week="2026-W09",
            institution_filter=["inst-1"],
            child_profile_id="4242",
            child_user_id="barn0003",
            all_child_user_ids=["barn0003"],
            guardian_login="guardian-1",
        )

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_a_portal_that_names_no_child_does_not_block_the_read(self, client, http):
        """Silence is not disagreement.

        Institutions whose answer omits ``child`` leave us where we were
        before this check existed, which is no reason to refuse them.
        """
        self._bootstrapped(client, [{"Id": "9001", "Login": "barn0003"}])
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {"loginId": "parent-42"}))
        http.route(EASYIQ_CALENDAR_URL, HttpResponse(200, [{"ItemType": 9, "Title": "Dansk"}]))

        events = await client.widgets.get_easyiq_calendar_events(
            week="2026-W09",
            institution_filter=["inst-1"],
            child_profile_id="4242",
            child_user_id="barn0003",
            all_child_user_ids=["barn0003"],
            guardian_login="guardian-1",
        )

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_the_refusal_names_no_identifier(self, client, http):
        """The message reaches the CLI, and both sides of it are UniLogins."""
        self._bootstrapped(client, [{"Id": "9001", "Login": "barn0003"}])
        http.route(EASYIQ_SWITCHCHILD_URL, HttpResponse(200, None))
        http.route(EASYIQ_AUTHENTICATE_URL, HttpResponse(200, {"child": "barn0004"}))

        with pytest.raises(EasyIQWrongChildSession) as excinfo:
            await client.widgets.get_easyiq_calendar_events(
                week="2026-W09",
                institution_filter=["inst-1"],
                child_profile_id="4242",
                child_user_id="barn0003",
                all_child_user_ids=["barn0003", "barn0004"],
                guardian_login="guardian-1",
            )

        assert "barn0003" not in str(excinfo.value)
        assert "barn0004" not in str(excinfo.value)
