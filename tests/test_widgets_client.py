"""Tests for widget token and provider endpoints."""

import asyncio
from unittest.mock import AsyncMock, Mock, call

import pytest

from aula.api_client import AulaApiClient
from aula.const import (
    CICERO_API,
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
    WIDGET_HUSKELISTEN,
    WIDGET_MIN_UDDANNELSE_TASKS,
    WIDGET_MIN_UDDANNELSE_UGEPLAN,
)
from aula.http import AulaNotFoundError

EASYIQ_CALENDAR_URL = f"{EASYIQ_PORTAL}{EASYIQ_CALENDAR_PATH}"
EASYIQ_HOMEWORK_URL = f"{EASYIQ_PORTAL}{EASYIQ_HOMEWORK_PATH}"


def _token_response(token: str) -> Mock:
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json = Mock(return_value={"data": token})
    return resp


def _calendar_response(payload: object) -> Mock:
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json = Mock(return_value=payload)
    return resp


class TestWidgetsClient:
    @pytest.fixture
    def client(self):
        client = AulaApiClient(http_client=AsyncMock(), access_token="token")
        # The EasyIQ portal session has its own tests below; marking it done
        # keeps the request-shape tests free of bootstrap plumbing.
        client.widgets._easyiq_session_ready = True
        return client

    @pytest.fixture
    def unbootstrapped_client(self):
        return AulaApiClient(http_client=AsyncMock(), access_token="token")

    @pytest.mark.asyncio
    async def test_get_bearer_token_calls_raise_for_status_before_json(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-123"})
        client._request_with_version_retry = AsyncMock(return_value=token_response)

        token = await client.widgets._get_bearer_token("0030")

        assert token == "Bearer token-123"
        client._request_with_version_retry.assert_awaited_once_with(
            "get", f"{client.api_url}?method=aulaToken.getAulaToken&widgetId=0030"
        )
        assert token_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_mu_tasks_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-123"})

        tasks_response = Mock()
        tasks_response.raise_for_status = Mock()
        tasks_response.json = Mock(
            return_value={
                "opgaver": [
                    {
                        "id": "task-1",
                        "title": "Task 1",
                    }
                ]
            }
        )

        client._request_with_version_retry = AsyncMock(side_effect=[token_response, tasks_response])

        tasks = await client.widgets.get_mu_tasks(
            widget_id=WIDGET_MIN_UDDANNELSE_TASKS,
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert [task.id for task in tasks] == ["task-1"]
        assert client._request_with_version_retry.await_count == 2

        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{MIN_UDDANNELSE_API}/opgaveliste")
        assert calls[1].kwargs["params"] == {
            "placement": "narrow",
            "sessionUUID": "session-1",
            "userProfile": "guardian",
            "currentWeekNumber": "2026-W09",
            "isMobileApp": "false",
            "childFilter[]": ["child-1"],
            "institutionFilter[]": ["inst-1"],
        }
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-123",
            "Accept": "application/json",
        }
        assert tasks_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_ugeplan_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-abc"})

        ugeplan_response = Mock()
        ugeplan_response.raise_for_status = Mock()
        ugeplan_response.json = Mock(
            return_value={"personer": [{"id": 1, "navn": "Student", "uniLogin": "student1"}]}
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, ugeplan_response]
        )

        persons = await client.widgets.get_ugeplan(
            widget_id=WIDGET_MIN_UDDANNELSE_UGEPLAN,
            child_filter=["child-1", "child-2"],
            institution_filter=["inst-1", "inst-2"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert [person.id for person in persons] == [1]
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{MIN_UDDANNELSE_API}/ugebrev")
        assert calls[1].kwargs["params"] == {
            "assuranceLevel": "3",
            "childFilter": "child-1,child-2",
            "currentWeekNumber": "2026-W09",
            "institutionFilter": "inst-1,inst-2",
            "isMobileApp": "false",
            "placement": "narrow",
            "sessionUUID": "session-1",
            "userProfile": "guardian",
        }
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-abc",
            "Accept": "application/json",
        }
        assert ugeplan_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-easy"})

        easyiq_response = Mock()
        easyiq_response.raise_for_status = Mock()
        easyiq_response.json = Mock(
            return_value={
                "data": {
                    "appointments": [
                        {
                            "appointmentId": "apt-1",
                            "title": "Math",
                            "start": "2026-02-24 08:00",
                            "end": "2026-02-24 09:00",
                            "description": "<p>Algebra</p>",
                            "itemType": 9,
                        }
                    ]
                }
            }
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, easyiq_response]
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
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("post", f"{EASYIQ_API}/weekplaninfo")
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-easy",
            "x-aula-institutionfilter": "inst-1,inst-2",
        }
        assert calls[1].kwargs["json"] == {
            "sessionId": "session-1",
            "currentWeekNr": "2026-W09",
            "userProfile": "guardian",
            "institutionFilter": ["inst-1", "inst-2"],
            "childFilter": ["child-1"],
        }
        assert easyiq_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_easyiq_homework_reads_the_homework_controller(self, client):
        """The calendar controller never returns homework; this one does."""
        homework_rows = _calendar_response(
            [
                {
                    "ItemType": 4,
                    "Start": "2026-02-28T00:00:00",
                    "Courses": "Dansk",
                    "Activities": "Læselektie",
                    "Description": "<p>Pages 40-55</p>",
                }
            ]
        )
        client._request_with_version_retry = AsyncMock(
            side_effect=[_token_response("token-easy-hw"), homework_rows]
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

        calls = client._request_with_version_retry.await_args_list
        assert calls[0].args == (
            "get",
            f"{client.api_url}?method=aulaToken.getAulaToken&widgetId={WIDGET_EASYIQ_HOMEWORK}",
        )
        assert calls[1].args == ("get", EASYIQ_HOMEWORK_URL)
        assert calls[1].kwargs["params"] == {
            "date": "2026-02-23T00:00:00Z",
            "activityFilter": "",
            "loginId": "4242",
        }
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-easy-hw",
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
    async def test_portal_session_is_established_before_any_controller(self, unbootstrapped_client):
        """Without AuthenticateAulaUser the portal's controllers all 500."""
        client = unbootstrapped_client
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-boot"),  # token for the bootstrap
                _calendar_response(None),  # AuthenticateAulaUser
                _calendar_response({"Children": [{"Id": "9001", "Login": "ASTR8360"}]}),
                _token_response("token-easy-hw"),  # token for the fetch
                _calendar_response([{"ItemType": 4, "CoursesDisplay": "Dansk"}]),
            ]
        )

        homework = await client.widgets.get_easyiq_homework(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "astr8360",
            child_profile_id="4242",
            all_child_user_ids=["astr8360", "kris37r9"],
        )

        assert [hw.subject for hw in homework] == ["Dansk"]
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("post", f"{EASYIQ_PORTAL}{EASYIQ_AUTHENTICATE_PATH}")
        assert calls[2].args == ("get", f"{EASYIQ_PORTAL}{EASYIQ_CHILDREN_PATH}")
        # EasyIQ's own ID is used as loginId, matched on Login not Name, and
        # x-childfilter carries every child while x-child carries this one.
        assert calls[4].kwargs["params"]["loginId"] == "9001"
        assert calls[4].kwargs["headers"]["x-child"] == "astr8360"
        assert calls[4].kwargs["headers"]["x-childfilter"] == "astr8360,kris37r9"

    @pytest.mark.asyncio
    async def test_portal_session_runs_once_across_calls(self, unbootstrapped_client):
        client = unbootstrapped_client
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-boot"),
                _calendar_response(None),
                _calendar_response({"Children": [{"Id": "9001", "Login": "astr8360"}]}),
                _token_response("token-easy-hw"),
                _calendar_response([{"ItemType": 4, "CoursesDisplay": "Dansk"}]),
                _token_response("token-easy-hw"),
                _calendar_response([{"ItemType": 4, "CoursesDisplay": "Matematik"}]),
            ]
        )
        kwargs = {
            "child_profile_id": "4242",
            "all_child_user_ids": ["astr8360"],
        }

        await client.widgets.get_easyiq_homework(
            "2026-W09", "guardian-1", ["inst-1"], "astr8360", **kwargs
        )
        homework = await client.widgets.get_easyiq_homework(
            "2026-W10", "guardian-1", ["inst-1"], "astr8360", **kwargs
        )

        assert [hw.subject for hw in homework] == ["Matematik"]
        assert client._request_with_version_retry.await_count == 7

    @pytest.mark.asyncio
    async def test_portal_session_runs_once_under_concurrency(self, unbootstrapped_client):
        """Callers reading several children at once share the one bootstrap.

        The ready flag alone does not settle this: every caller sees it unset
        while the first is still awaiting the POST, so each would sign in
        again and the portal would be asked to open a session per child.
        """
        client = unbootstrapped_client
        authenticate_calls = 0

        async def _dispatch(method, url, **kwargs):
            nonlocal authenticate_calls
            # Yield, so the callers really do interleave inside the bootstrap
            # rather than each running start to finish.
            await asyncio.sleep(0)
            if "getAulaToken" in url:
                return _token_response("token-boot")
            if url.endswith(EASYIQ_AUTHENTICATE_PATH):
                authenticate_calls += 1
                return _calendar_response(None)
            if url.endswith(EASYIQ_CHILDREN_PATH):
                return _calendar_response({"Children": [{"Id": "9001", "Login": "astr8360"}]})
            raise AssertionError(f"unexpected request: {url}")

        client._request_with_version_retry = _dispatch

        await asyncio.gather(
            *(
                client.widgets.ensure_easyiq_session(
                    ["inst-1"], "guardian-1", ["astr8360", "kris37r9"]
                )
                for _ in range(4)
            )
        )

        assert authenticate_calls == 1
        assert client.widgets.resolve_easyiq_child_id("astr8360") == "9001"

    @pytest.mark.asyncio
    async def test_a_failed_bootstrap_leaves_the_guessing_fallback(self, unbootstrapped_client):
        """Institutions this flow does not suit must still get the old path."""
        client = unbootstrapped_client
        failing = Mock()
        failing.raise_for_status = Mock(side_effect=AulaNotFoundError("HTTP 404", 404))
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-boot"),
                failing,  # AuthenticateAulaUser
                _token_response("token-easy-hw"),
                _calendar_response([{"ItemType": 4, "CoursesDisplay": "Dansk"}]),
            ]
        )

        homework = await client.widgets.get_easyiq_homework(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "astr8360",
            child_profile_id="4242",
            all_child_user_ids=["astr8360"],
        )

        assert [hw.subject for hw in homework] == ["Dansk"]
        calls = client._request_with_version_retry.await_args_list
        assert calls[3].kwargs["params"]["loginId"] == "4242"

    @pytest.mark.asyncio
    async def test_get_easyiq_homework_keeps_rows_of_an_unfamiliar_item_type(self, client):
        """The controller only serves homework, so never report nothing instead."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy-hw"),
                _calendar_response([{"ItemType": 11, "Courses": "Dansk"}]),
            ]
        )

        homework = await client.widgets.get_easyiq_homework(
            week="2026-W09",
            session_uuid="guardian-1",
            institution_filter=["inst-1"],
            child_id="child-user-1",
            child_profile_id="4242",
        )

        assert [hw.subject for hw in homework] == ["Dansk"]

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_does_not_use_the_homework_controller(self, client):
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy"),
                _calendar_response({"data": {"appointments": []}}),
                _token_response("token-easy"),
                _calendar_response([{"itemType": 9, "courses": "Matematik"}]),
            ]
        )

        await client.widgets.get_easyiq_weekplan(
            "2026-W09", "guardian-1", ["inst-1"], "child-user-1", child_profile_id="4242"
        )

        calls = client._request_with_version_retry.await_args_list
        assert calls[3].args == ("get", EASYIQ_CALENDAR_URL)

    @pytest.mark.asyncio
    async def test_easyiq_calendar_falls_through_to_the_accepted_identifiers(self, client):
        """EasyIQ answers 200-with-nothing for identifiers it does not know."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy"),
                _calendar_response([]),  # profile login / user child
                _calendar_response([{"itemType": 4, "courses": "Dansk"}]),  # user login
            ]
        )

        homework = await client.widgets.get_easyiq_homework(
            week="2026-W09",
            session_uuid="guardian-1",
            institution_filter=["inst-1"],
            child_id="child-user-1",
            child_profile_id="4242",
        )

        assert [hw.subject for hw in homework] == ["Dansk"]
        calls = client._request_with_version_retry.await_args_list
        assert [c.kwargs["params"]["loginId"] for c in calls[1:]] == ["4242", "child-user-1"]

    @pytest.mark.asyncio
    async def test_easyiq_calendar_reuses_the_identifiers_that_worked(self, client):
        """A second week must not re-probe every identifier combination."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy"),
                _calendar_response([]),
                _calendar_response([{"itemType": 4, "courses": "Dansk"}]),
                _token_response("token-easy"),
                _calendar_response([{"itemType": 4, "courses": "Matematik"}]),
            ]
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
        calls = client._request_with_version_retry.await_args_list
        assert len(calls) == 5
        assert calls[4].kwargs["params"]["loginId"] == "child-user-1"

    @pytest.mark.asyncio
    async def test_easyiq_calendar_raises_when_every_identifier_is_rejected(self, client):
        rejected = Mock()
        rejected.raise_for_status = Mock(side_effect=AulaNotFoundError("HTTP 404", 404))
        client._request_with_version_retry = AsyncMock(
            side_effect=[_token_response("token-easy"), rejected, rejected, rejected, rejected]
        )

        with pytest.raises(AulaNotFoundError):
            await client.widgets.get_easyiq_homework(
                week="2026-W09",
                session_uuid="guardian-1",
                institution_filter=["inst-1"],
                child_id="child-user-1",
                child_profile_id="4242",
            )

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_falls_back_to_the_portal_when_the_api_fails(self, client):
        failing = Mock()
        failing.raise_for_status = Mock(side_effect=AulaNotFoundError("HTTP 404", 404))
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy"),
                failing,
                _token_response("token-easy"),
                _calendar_response(
                    [
                        {
                            "itemType": 9,
                            "courses": "Matematik",
                            "activitiesDisplay": "6A",
                            "start": "2026-02-24T08:00:00",
                        },
                        {"itemType": 4, "courses": "Dansk"},
                    ]
                ),
            ]
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
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("post", f"{EASYIQ_API}/weekplaninfo")
        assert calls[3].args == ("get", EASYIQ_CALENDAR_URL)

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_falls_back_when_the_api_returns_nothing(self, client):
        """A 200 with an empty appointment list is the shape issue #45 reported."""
        empty = Mock()
        empty.raise_for_status = Mock()
        empty.json = Mock(return_value={"data": {"appointments": []}})
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy"),
                empty,
                _token_response("token-easy"),
                _calendar_response([{"itemType": 8, "courses": "Idræt"}]),
            ]
        )

        appointments = await client.widgets.get_easyiq_weekplan(
            "2026-W09",
            "guardian-1",
            ["inst-1"],
            "child-user-1",
            child_profile_id="4242",
        )

        assert [a.title for a in appointments] == ["Idræt"]

    @pytest.mark.asyncio
    async def test_easyiq_calendar_warns_when_the_body_carries_no_events(self, client, caplog):
        """A licensing error arrives as 2xx with an error object; silence reads as an empty week."""
        envelope = {"ErrorCode": "1", "ErrorDescription": "No license for this school"}
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy"),
                *[_calendar_response(envelope)] * 4,
            ]
        )

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
    async def test_easyiq_calendar_stays_quiet_on_a_genuinely_empty_week(self, client, caplog):
        client._request_with_version_retry = AsyncMock(
            side_effect=[_token_response("token-easy"), *[_calendar_response([])] * 4]
        )

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
    async def test_easyiq_calendar_truncates_a_long_body(self, client, caplog):
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy"),
                *[_calendar_response({"error": "x" * 5000})] * 4,
            ]
        )

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
    async def test_weekplaninfo_warns_when_the_envelope_is_missing(self, client, caplog):
        """weekplaninfo has the same hole: no data key, and the fallback hides why."""
        envelope = _calendar_response({"ErrorCode": "1", "ErrorDescription": "Not licensed"})
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy"),
                envelope,
                _token_response("token-easy"),
                _calendar_response([{"itemType": 8, "courses": "Idræt"}]),
            ]
        )

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
    async def test_weekplaninfo_stays_quiet_on_an_explicit_null_envelope(self, client, caplog):
        """A null under "data" is the API saying it has none, not a shape we cannot read."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-easy"),
                _calendar_response({"data": None}),
                _token_response("token-easy"),
                _calendar_response([{"itemType": 8, "courses": "Idræt"}]),
            ]
        )

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
    async def test_get_easyiq_weekplan_raises_when_no_profile_id_to_fall_back_with(self, client):
        failing = Mock()
        failing.raise_for_status = Mock(side_effect=AulaNotFoundError("HTTP 404", 404))
        client._request_with_version_retry = AsyncMock(
            side_effect=[_token_response("token-easy"), failing]
        )

        with pytest.raises(AulaNotFoundError):
            await client.widgets.get_easyiq_weekplan(
                "2026-W09", "guardian-1", ["inst-1"], "child-user-1"
            )

    @pytest.mark.asyncio
    async def test_get_meebook_weekplan_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-meebook"})

        meebook_response = Mock()
        meebook_response.raise_for_status = Mock()
        meebook_response.json = Mock(
            return_value=[
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
            ]
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, meebook_response]
        )

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W9",
            session_uuid="session-1",
        )

        assert [plan.unilogin for plan in plans] == ["student1"]
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{MEEBOOK_API}/relatedweekplan/all")
        assert calls[1].kwargs["params"] == {
            "currentWeekNumber": "2026-W09",
            "userProfile": "guardian",
            "childFilter[]": ["child-1"],
            "institutionFilter[]": ["inst-1"],
        }
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-meebook",
            "Accept": "application/json",
            "sessionUUID": "session-1",
            "X-Version": "1.0",
        }
        assert meebook_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_momo_courses_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-momo"})

        momo_response = Mock()
        momo_response.raise_for_status = Mock()
        momo_response.json = Mock(
            return_value=[
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
            ]
        )

        client._request_with_version_retry = AsyncMock(side_effect=[token_response, momo_response])

        courses = await client.widgets.get_momo_courses(
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
        )

        assert [course.user_id for course in courses] == ["child-1"]
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{SYSTEMATIC_API}/courses/v1")
        assert calls[1].kwargs["params"] == {
            "widgetVersion": "1.3",
            "userProfile": "guardian",
            "sessionId": "session-1",
            "children": ["child-1"],
            "institutions": ["inst-1"],
        }
        assert calls[1].kwargs["headers"] == {
            "Aula-Authorization": "Bearer token-momo",
        }
        assert momo_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_momo_reminders_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-momo"})

        reminders_response = Mock()
        reminders_response.raise_for_status = Mock()
        reminders_response.json = Mock(
            return_value=[
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
            ]
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, reminders_response]
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

        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{SYSTEMATIC_API}/reminders/v1")
        assert calls[1].kwargs["params"] == {
            "widgetVersion": "1.10",
            "userProfile": "guardian",
            "sessionId": "session-1",
            "children": ["child-1"],
            "institutions": ["inst-1"],
            "from": "2026-02-26",
            "dueNoLaterThan": "2026-03-05",
        }
        assert calls[1].kwargs["headers"] == {
            "Aula-Authorization": "Bearer token-momo",
        }
        assert reminders_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_library_status_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-library"})

        library_response = Mock()
        library_response.raise_for_status = Mock()
        library_response.json = Mock(
            return_value={
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
            }
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, library_response]
        )

        status = await client.widgets.get_library_status(
            widget_id=WIDGET_HUSKELISTEN,
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
        )

        assert [loan.id for loan in status.loans] == [1]
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{CICERO_API}/library/status/v3")
        assert calls[1].kwargs["params"] == {
            "coverImageHeight": "160",
            "widgetVersion": "1.6",
            "userProfile": "guardian",
            "sessionUUID": "session-1",
            "institutions": ["inst-1"],
            "children": ["child-1"],
        }
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-library",
            "Accept": "application/json",
        }
        assert library_response.method_calls == [call.raise_for_status(), call.json()]


class TestWidgetsClientMalformedResponses:
    """Providers sometimes answer 2xx with an error object instead of an array.

    Meebook returns ``{"message": "JWT-Token expired, please renew."}`` when its
    widget token has expired; iterating that yields the keys as strings.
    """

    JWT_EXPIRED = {"message": "JWT-Token expired, please renew."}

    @pytest.fixture
    def client(self):
        return AulaApiClient(http_client=AsyncMock(), access_token="token")

    @staticmethod
    def _responses(client, body):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-123"})

        provider_response = Mock()
        provider_response.raise_for_status = Mock()
        provider_response.json = Mock(return_value=body)

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, provider_response]
        )

    @pytest.mark.asyncio
    async def test_meebook_weekplan_returns_empty_on_jwt_expiry_message(self, client, caplog):
        self._responses(client, self.JWT_EXPIRED)

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert plans == []
        assert "Meebook weekplan returned dict instead of a list" in caplog.text
        assert "JWT-Token expired" in caplog.text

    @pytest.mark.asyncio
    async def test_meebook_weekplan_skips_non_dict_items(self, client, caplog):
        self._responses(client, [{"name": "Child", "unilogin": "abc123"}, "junk", None])

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert [plan.name for plan in plans] == ["Child"]
        assert "Meebook weekplan returned 2 non-dict item(s)" in caplog.text

    @pytest.mark.asyncio
    async def test_meebook_weekplan_returns_empty_on_unparseable_body(self, client):
        # http_httpx sets data to None when the body is not valid JSON.
        self._responses(client, None)

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert plans == []

    @pytest.mark.asyncio
    async def test_momo_courses_returns_empty_on_error_object(self, client, caplog):
        self._responses(client, self.JWT_EXPIRED)

        courses = await client.widgets.get_momo_courses(
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
        )

        assert courses == []
        assert "Huskelisten courses returned dict instead of a list" in caplog.text

    @pytest.mark.asyncio
    async def test_momo_reminders_returns_empty_on_error_object(self, client, caplog):
        self._responses(client, self.JWT_EXPIRED)

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
    async def test_library_status_returns_empty_on_list_body(self, client, caplog):
        self._responses(client, ["unexpected"])

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
    def client(self):
        return AulaApiClient(http_client=AsyncMock(), access_token="token")

    @pytest.mark.asyncio
    async def test_authenticate_response_populates_the_parent_login_id(self, client):
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-boot"),
                _calendar_response({"loginId": "parent-42", "child": "1", "schoolId": "9"}),
                _calendar_response({"Children": []}),
            ]
        )

        await client.widgets.ensure_easyiq_session(["inst-1"], "guardian-1", ["astr8360"])

        assert client.widgets._easyiq_parent_login_id == "parent-42"

    @pytest.mark.asyncio
    async def test_authenticate_response_missing_login_id_does_not_raise(self, client):
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-boot"),
                _calendar_response({"loginTypeId": "1"}),  # no loginId at all
                _calendar_response({"Children": []}),
            ]
        )

        await client.widgets.ensure_easyiq_session(["inst-1"], "guardian-1", ["astr8360"])

        assert client.widgets._easyiq_parent_login_id is None

    @pytest.mark.asyncio
    async def test_authenticate_response_unparseable_body_does_not_raise(self, client):
        unparseable = Mock()
        unparseable.raise_for_status = Mock()
        unparseable.json = Mock(side_effect=ValueError("not json"))
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-boot"),
                unparseable,
                _calendar_response({"Children": []}),
            ]
        )

        await client.widgets.ensure_easyiq_session(["inst-1"], "guardian-1", ["astr8360"])

        assert client.widgets._easyiq_parent_login_id is None
        # A bad AuthenticateAulaUser body is not fatal: GetChildren still runs.
        assert client._request_with_version_retry.await_count == 3

    @pytest.mark.asyncio
    async def test_get_children_stores_the_real_login_string_and_id(self, client):
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                _token_response("token-boot"),
                _calendar_response({}),
                _calendar_response({"Children": [{"Id": "9001", "Login": "ASTR8360"}]}),
            ]
        )

        await client.widgets.ensure_easyiq_session(["inst-1"], "guardian-1", ["astr8360"])

        assert client.widgets.resolve_easyiq_child_id("astr8360") == "9001"
        # The real casing survives, even though the lookup key is casefolded.
        assert client.widgets.resolve_easyiq_child_login("astr8360") == "ASTR8360"

    def test_identifier_variants_lead_with_the_protocol_correct_pair(self, client):
        client.widgets._easyiq_parent_login_id = "parent-42"
        client.widgets._easyiq_child_logins["astr8360"] = "ASTR8360"

        variants = client.widgets.easyiq_identifier_variants(
            "4242", "astr8360", "guardian-1", "9001"
        )

        assert variants[0] == ("parent-42", "ASTR8360")
        # The rest of the fallback order is unchanged.
        assert variants[1:] == [
            ("9001", "astr8360"),
            ("4242", "astr8360"),
            ("astr8360", "astr8360"),
            ("4242", "4242"),
            ("guardian-1", "astr8360"),
        ]

    def test_identifier_variants_fall_back_unchanged_without_the_protocol_pair(self, client):
        variants = client.widgets.easyiq_identifier_variants(
            "4242", "astr8360", "guardian-1", "9001"
        )

        assert variants == [
            ("9001", "astr8360"),
            ("4242", "astr8360"),
            ("astr8360", "astr8360"),
            ("4242", "4242"),
            ("guardian-1", "astr8360"),
        ]

    def test_identifier_variants_need_both_halves_of_the_protocol_pair(self, client):
        """A parent loginId with no matching real Login is not enough."""
        client.widgets._easyiq_parent_login_id = "parent-42"

        variants = client.widgets.easyiq_identifier_variants("4242", "astr8360", "guardian-1")

        assert ("parent-42", "astr8360") not in variants

    @pytest.mark.asyncio
    async def test_switch_child_posts_the_easyiq_id_as_login_id(self, client):
        client._request_with_version_retry = AsyncMock(
            side_effect=[_token_response("token-switch"), _calendar_response(None)]
        )

        await client.widgets.switch_easyiq_child(
            "9001", ["inst-1"], "guardian-1", ["astr8360", "kris37r9"], "astr8360"
        )

        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("post", f"{EASYIQ_PORTAL}{EASYIQ_SWITCHCHILD_PATH}")
        # loginId is the Id GetChildren gave for this child -- not its Login,
        # and not Aula's own userId.
        assert calls[1].kwargs["params"] == {"loginId": "9001"}
        assert calls[1].kwargs["headers"]["x-child"] == "astr8360"
