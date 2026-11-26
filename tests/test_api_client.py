"""Tests for aula.api_client."""

import inspect
import logging
from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from aula.api_client import AulaApiClient, ThreadScanLimitError, validate_vacation
from aula.const import API_URL, API_VERSION
from aula.http import (
    AulaAuthenticationError,
    AulaConnectionError,
    AulaRejectedError,
    AulaResponseError,
    AulaServerError,
    AulaSessionExpiredError,
    DownloadTooLargeError,
    HttpRequestError,
    HttpResponse,
)
from aula.http_httpx import HttpxHttpClient
from tests.fakes import FakeHttpClient, http_status, ok, rejected

PROFILES = "profiles.getProfilesByLogin"
CONTEXT = "profiles.getProfileContext"
DAILY_OVERVIEW = "presence.getDailyOverview"
TEMPLATES = "presence.getPresenceTemplates"
REGISTRATIONS = "presence.getPresenceRegistrations"
REGISTRATION_DETAIL = "presence.getPresenceRegistrationDetail"
STATES = "presence.getPresenceStates"
CONFIGURATION = "presence.getPresenceConfigurationByChildIds"
VACATIONS = "presence.getVacationRegistrationsByChildren"
ACTIVITY = "presence.getActivityOverview"
UPDATE_TEMPLATE = "presence.updatePresenceTemplate"
UPDATE_STATUS = "presence.updateStatusByInstitutionProfileIds"
ADD_VACATION = "calendar.addVacation"


def search_hit(message):
    """A search.findMessage result: the thread, with the message inside."""
    return {"threadId": 1, "thread": {"id": "1", "subject": "Subject"}, "searchMessage": message}


def thread_item(thread_id, send_date_time):
    """A messaging.getThreads item, dated by its latest message like the live API."""
    return {
        "id": thread_id,
        "subject": "Emne Et",
        "latestMessage": {"id": "1000003", "sendDateTime": send_date_time},
    }


class TestGetProfile:
    """Tests for AulaApiClient.get_profile method."""

    @pytest.fixture
    def http(self):
        http = FakeHttpClient()
        http.aula(CONTEXT, ok({}))
        return http

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @staticmethod
    def _answer_profiles(http, profiles):
        http.aula(PROFILES, ok({"profiles": profiles}))

    @pytest.mark.asyncio
    async def test_get_profile_happy_path(self, client, http):
        """Valid profile response is parsed correctly."""
        profile_data = {
            "profileId": 123,
            "displayName": "Værge Et",
            "children": [
                {
                    "id": 456,
                    "profileId": 789,
                    "name": "Barn Et",
                    "institutionProfiles": [{"id": 456, "institutionName": "Skole Et"}],
                }
            ],
            "institutionProfiles": [{"id": 100}],
        }
        self._answer_profiles(http, [profile_data])
        profile = await client.get_profile()
        assert profile.profile_id == 123
        assert profile.display_name == "Værge Et"
        assert len(profile.children) == 1
        assert profile.children[0].id == 456
        assert len(http.calls(PROFILES)) == 1

    @pytest.mark.asyncio
    async def test_get_profile_empty_profiles_raises(self, client, http):
        """Empty profiles list raises ValueError."""
        self._answer_profiles(http, [])
        with pytest.raises(ValueError, match="No profile data found"):
            await client.get_profile()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("profiles", [{"profileId": 900001}, ["profile"], "profile"])
    async def test_profiles_that_are_not_a_list_of_objects_are_an_aula_response_error(
        self, client, http, profiles
    ):
        self._answer_profiles(http, profiles)
        with pytest.raises(AulaResponseError):
            await client.get_profile()

    @pytest.mark.asyncio
    async def test_a_profile_that_does_not_parse_is_an_aula_response_error(self, client, http):
        self._answer_profiles(http, [{"profileId": "not a number"}])
        with pytest.raises(AulaResponseError, match="main profile") as exc_info:
            await client.get_profile()
        assert isinstance(exc_info.value.__cause__, ValueError)

    @pytest.mark.asyncio
    async def test_institution_profiles_that_are_not_a_list_are_an_aula_response_error(
        self, client, http
    ):
        self._answer_profiles(http, [{"profileId": 900001, "institutionProfiles": "1000001"}])
        with pytest.raises(AulaResponseError):
            await client.get_profile()

    @pytest.mark.asyncio
    async def test_get_profile_no_children(self, client, http):
        """Profile with no children returns empty children list."""
        profile_data = {
            "profileId": 123,
            "displayName": "Værge Et",
            "children": [],
            "institutionProfiles": [],
        }
        self._answer_profiles(http, [profile_data])
        profile = await client.get_profile()
        assert profile.children == []

    @pytest.mark.asyncio
    async def test_get_profile_malformed_child_skipped(self, client, http):
        """Malformed child entry is skipped with warning."""
        profile_data = {
            "profileId": 123,
            "displayName": "Værge Et",
            "children": [
                "not a dict",
                {
                    "id": 456,
                    "profileId": 789,
                    "name": "Barn Et",
                    "institutionProfiles": [{"id": 456, "institutionName": "Skole Et"}],
                },
            ],
            "institutionProfiles": [],
        }
        self._answer_profiles(http, [profile_data])
        profile = await client.get_profile()
        assert len(profile.children) == 1

    def _profile_with_own_child(self):
        return {
            "profileId": 123,
            "displayName": "Forælder",
            "children": [
                {
                    "id": 1,
                    "profileId": 11,
                    "name": "Barn Et",
                    "institutionProfile": {"institutionName": "Skole A", "institutionCode": "A1"},
                }
            ],
            "institutionProfiles": [],
        }

    @pytest.mark.asyncio
    async def test_get_profile_adds_extended_access_children(self, client, http):
        """Children only listed in getProfileContext are added after the own children."""
        own_in_context = {"id": 1, "profileId": 11, "name": "Barn Et", "institutionCode": "A1"}
        extended = {
            "id": 2,
            "profileId": 22,
            "name": "Barn To",
            "userId": "barn2",
            "institutionCode": "B2",
        }
        self._answer_profiles(http, [self._profile_with_own_child()])
        http.aula(
            CONTEXT,
            ok({"institutions": [{"name": "Skole B", "children": [extended, own_in_context]}]}),
        )
        profile = await client.get_profile()
        assert [c.id for c in profile.children] == [1, 2]
        assert profile.children[1].institution_name == "Skole B"
        assert profile.children[1].institution_code == "B2"
        assert profile.children[1].user_id == "barn2"
        assert profile.institution_profile_ids == [1, 2]
        assert http.calls(CONTEXT)[0].query["portalrole"] == "guardian"

    @pytest.mark.asyncio
    async def test_get_profile_context_failure_keeps_own_children(self, client, http):
        self._answer_profiles(http, [self._profile_with_own_child()])
        http.aula(CONTEXT, http_status(500))
        profile = await client.get_profile()
        assert [c.id for c in profile.children] == [1]

    @pytest.mark.asyncio
    async def test_unparsable_extended_access_child_keeps_own_children(self, client, http):
        self._answer_profiles(http, [self._profile_with_own_child()])
        http.aula(CONTEXT, ok({"institutions": [{"name": "Skole Et", "children": [{"id": 2}]}]}))
        profile = await client.get_profile()
        assert [c.id for c in profile.children] == [1]

    @pytest.mark.asyncio
    async def test_extended_access_children_that_all_fail_never_raise(self, client, http):
        """The lookup is best effort, so its failures never cost the caller the profile."""
        self._answer_profiles(http, [{"profileId": 900001, "children": []}])
        http.aula(
            CONTEXT, ok({"institutions": [{"name": "Skole Et", "children": [{"id": 2}, "2"]}]})
        )
        profile = await client.get_profile()
        assert profile.children == []

    @pytest.mark.asyncio
    async def test_get_profile_context_without_institutions(self, client, http):
        self._answer_profiles(http, [self._profile_with_own_child()])
        http.aula(CONTEXT, ok(None))
        profile = await client.get_profile()
        assert [c.id for c in profile.children] == [1]

    @pytest.mark.asyncio
    async def test_get_profile_http_401_raises_auth_error(self, client, http):
        """401 response raises AulaAuthenticationError."""
        http.aula(PROFILES, http_status(401))
        with pytest.raises(AulaAuthenticationError):
            await client.get_profile()

    @pytest.mark.asyncio
    async def test_get_profile_http_500_raises_server_error(self, client, http):
        """500 response raises AulaServerError."""
        http.aula(PROFILES, http_status(500))
        with pytest.raises(AulaServerError):
            await client.get_profile()


class TestIsLoggedIn:
    """Tests for AulaApiClient.is_logged_in method."""

    @pytest.fixture
    def http(self):
        http = FakeHttpClient()
        http.aula(CONTEXT, ok({}))
        return http

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @pytest.mark.asyncio
    async def test_is_logged_in_returns_true(self, client, http):
        """Returns True when get_profile succeeds."""
        profile_data = {
            "profileId": 123,
            "displayName": "Værge Et",
            "children": [],
            "institutionProfiles": [],
        }
        http.aula(PROFILES, ok({"profiles": [profile_data]}))
        assert await client.is_logged_in() is True

    @pytest.mark.asyncio
    async def test_is_logged_in_returns_false_on_error(self, client, http):
        """Returns False when get_profile raises any exception."""
        http.aula(PROFILES, http_status(401))
        assert await client.is_logged_in() is False


class TestGetDailyOverview:
    """Tests for AulaApiClient.get_daily_overview method."""

    @pytest.fixture
    def http(self):
        return FakeHttpClient()

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @pytest.mark.asyncio
    async def test_happy_path(self, client, http):
        """Valid daily overview response is parsed."""
        overview_data = {
            "status": 1,
            "institutionProfile": {
                "id": 456,
                "institutionName": "Skole Et",
            },
        }
        http.aula(DAILY_OVERVIEW, ok([overview_data]))
        result = await client.get_daily_overview(456)
        assert result is not None
        assert result.status is not None
        assert http.calls(DAILY_OVERVIEW)[0].query["childIds[]"] == "456"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", [[], None])
    async def test_a_day_without_an_overview_returns_none_quietly(self, client, http, caplog, data):
        http.aula(DAILY_OVERVIEW, ok(data))
        with caplog.at_level(logging.WARNING, logger="aula"):
            result = await client.get_daily_overview(456)
        assert result is None
        assert all(r.levelno < logging.WARNING for r in caplog.records)

    @pytest.mark.asyncio
    async def test_http_error_raises(self, client, http):
        """HTTP errors are raised."""
        http.aula(DAILY_OVERVIEW, http_status(500))
        with pytest.raises(AulaServerError):
            await client.get_daily_overview(456)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", [{"status": 1}, "overview", [None], [["status", 1]]])
    async def test_data_that_is_not_a_list_of_overviews_is_an_aula_response_error(
        self, client, http, data
    ):
        http.aula(DAILY_OVERVIEW, ok(data))
        with pytest.raises(AulaResponseError):
            await client.get_daily_overview(456)

    @pytest.mark.asyncio
    async def test_an_overview_that_fails_to_parse_keeps_the_cause(self, client, http):
        http.aula(DAILY_OVERVIEW, ok([{"location": 5}]))
        with (
            patch("aula.api_client.DailyOverview.from_dict", side_effect=KeyError("institution")),
            pytest.raises(AulaResponseError) as exc_info,
        ):
            await client.get_daily_overview(456)
        assert isinstance(exc_info.value.__cause__, KeyError)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [None, ["overview"], "overview"])
    async def test_a_body_that_is_not_an_envelope_is_an_aula_response_error(
        self, client, http, body
    ):
        http.aula(DAILY_OVERVIEW, http_status(200, body))
        with pytest.raises(AulaResponseError):
            await client.get_daily_overview(456)


class TestGetMessageThreads:
    """Tests for AulaApiClient.get_message_threads method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        """Valid threads response is parsed."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "threads": [
                            {"id": "t1", "subject": "Hello"},
                            {"id": "t2", "subject": "World"},
                        ]
                    }
                },
            )
        )
        threads = await client.get_message_threads()
        assert len(threads) == 2
        assert threads[0].subject == "Hello"

    @pytest.mark.asyncio
    async def test_threads_carry_their_parsed_fields(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "threads": [
                            {
                                "id": 1000001,
                                "subject": "Emne Et",
                                "read": True,
                                "latestMessage": {
                                    "id": "1000003",
                                    "sendDateTime": "2026-11-03T14:30:00+01:00",
                                    "text": {"html": "<p>Besked Et</p>"},
                                },
                                "recipients": [{"fullName": "Værge Et", "shortName": "VE"}],
                                "regardingChildren": [
                                    {"profileId": 1000008, "displayName": "Barn Et"}
                                ],
                            }
                        ]
                    }
                },
            )
        )
        [thread] = await client.get_message_threads()
        assert thread.thread_id == "1000001"
        assert thread.is_read is True
        assert thread.last_updated == datetime.fromisoformat("2026-11-03T14:30:00+01:00")
        assert thread.latest_message is not None
        assert thread.latest_message.text == "Besked Et"
        assert [r.full_name for r in thread.recipients] == ["Værge Et"]
        assert [c.profile_id for c in thread.regarding_children] == [1000008]

    @pytest.mark.asyncio
    async def test_empty_threads(self, client):
        """Empty threads list returns empty."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": {"threads": []}})
        )
        assert await client.get_message_threads() == []

    @pytest.mark.asyncio
    async def test_malformed_thread_skipped(self, client, caplog):
        """Malformed thread entry is skipped."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "threads": [
                            {"id": "t1", "subject": "Good"},
                            {"id": "t2", "subject": "Also Good"},
                        ]
                    }
                },
            )
        )
        threads = await client.get_message_threads()
        assert len(threads) == 2

    @pytest.mark.asyncio
    async def test_a_thread_that_is_not_an_object_is_skipped(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"threads": ["t1", {"id": "t2", "subject": "Good"}]}},
            )
        )
        threads = await client.get_message_threads()
        assert [thread.thread_id for thread in threads] == ["t2"]


class TestGetMessagesForThread:
    """Tests for AulaApiClient.get_messages_for_thread method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        """Valid messages response is parsed."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "messages": [
                            {
                                "id": "m1",
                                "messageType": "Message",
                                "text": {"html": "<p>Hello</p>"},
                            }
                        ]
                    }
                },
            )
        )
        messages = await client.get_messages_for_thread("t1", limit=5)
        assert len(messages) == 1
        assert messages[0].id == "m1"

    @pytest.mark.asyncio
    async def test_non_message_type_skipped(self, client):
        """Non-Message types are skipped."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "messages": [
                            {"id": "m1", "messageType": "SystemMessage", "text": "hi"},
                            {
                                "id": "m2",
                                "messageType": "Message",
                                "text": {"html": "<p>Real</p>"},
                            },
                        ]
                    }
                },
            )
        )
        messages = await client.get_messages_for_thread("t1", limit=5)
        assert len(messages) == 1
        assert messages[0].id == "m2"

    @pytest.mark.asyncio
    async def test_limit_respected(self, client):
        """Limit on number of messages is respected."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "messages": [
                            {
                                "id": f"m{i}",
                                "messageType": "Message",
                                "text": {"html": f"<p>{i}</p>"},
                            }
                            for i in range(10)
                        ]
                    }
                },
            )
        )
        messages = await client.get_messages_for_thread("t1", limit=3)
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_a_message_that_is_not_an_object_is_skipped(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "messages": [
                            "m1",
                            {"id": "m2", "messageType": "Message", "text": {"html": "<p>2</p>"}},
                        ]
                    }
                },
            )
        )
        messages = await client.get_messages_for_thread("t1", limit=5)
        assert [message.id for message in messages] == ["m2"]


class TestGetPresenceTemplates:
    """Tests for AulaApiClient.get_presence_templates method."""

    @pytest.fixture
    def http(self):
        return FakeHttpClient()

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @pytest.mark.asyncio
    async def test_get_presence_templates_happy_path(self, client, http):
        """Test fetching presence templates with valid data."""
        from aula.models.presence_template import PresenceWeekTemplate

        data = {
            "presenceWeekTemplates": [
                {
                    "institutionProfile": {
                        "id": 10,
                        "profileId": 99,
                        "institutionName": "Skole Et",
                    },
                    "dayTemplates": [
                        {
                            "id": 1,
                            "byDate": "2026-02-25",
                            "entryTime": "08:00",
                            "exitTime": "16:00",
                        }
                    ],
                }
            ]
        }

        http.aula(TEMPLATES, ok(data))

        result = await client.get_presence_templates(
            [10, 20],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert http.calls(TEMPLATES)[0].query == {
            "method": TEMPLATES,
            "filterInstitutionProfileIds[]": [10, 20],
            "fromDate": "2026-02-25",
            "toDate": "2026-02-25",
        }
        assert len(result) == 1
        assert isinstance(result[0], PresenceWeekTemplate)
        assert result[0].institution_profile is not None
        assert result[0].institution_profile.id == 10
        assert len(result[0].day_templates) == 1
        assert result[0].day_templates[0].by_date == "2026-02-25"

    @pytest.mark.asyncio
    async def test_get_presence_templates_empty_list(self, client, http):
        """Test fetching with empty templates list."""
        http.aula(TEMPLATES, ok({"presenceWeekTemplates": []}))

        result = await client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_null_data(self, client, http):
        """Test handling when data field is null."""
        http.aula(TEMPLATES, ok(None))

        result = await client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_null_presenceWeekTemplates(self, client, http):
        """Test handling when presenceWeekTemplates is null."""
        http.aula(TEMPLATES, ok({"presenceWeekTemplates": None}))

        result = await client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_null_items_in_list(self, client, http):
        """Test handling when list contains null items."""
        data = {
            "presenceWeekTemplates": [
                {
                    "institutionProfile": {"id": 10},
                    "dayTemplates": [{"id": 1, "byDate": "2026-02-25"}],
                },
                None,  # null item should be skipped
                {
                    "institutionProfile": {"id": 20},
                    "dayTemplates": [{"id": 2, "byDate": "2026-02-25"}],
                },
            ]
        }

        http.aula(TEMPLATES, ok(data))

        result = await client.get_presence_templates(
            [10, 20],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        # Should skip the null item and return 2 valid templates
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_presence_templates_malformed_item(self, client, http, caplog):
        """Test handling of malformed template item."""
        data = {
            "presenceWeekTemplates": [
                {
                    "institutionProfile": {"id": 10},
                    "dayTemplates": [{"id": 1, "byDate": "2026-02-25"}],
                },
                {
                    "dayTemplates": [{"id": 2}],
                    # Missing institutionProfile - might cause error
                },
                {
                    "institutionProfile": {"id": 30},
                    "dayTemplates": [{"id": 3, "byDate": "2026-02-26"}],
                },
            ]
        }

        http.aula(TEMPLATES, ok(data))

        with caplog.at_level("WARNING"):
            result = await client.get_presence_templates(
                [10, 20, 30],
                date(2026, 2, 25),
                date(2026, 2, 25),
            )

        # Should return valid templates and skip/log the malformed one
        assert len(result) >= 2  # At least the two valid ones

    @pytest.mark.asyncio
    async def test_get_presence_templates_non_list_presenceWeekTemplates_raises(self, client, http):
        http.aula(TEMPLATES, ok({"presenceWeekTemplates": "not a list"}))

        with pytest.raises(AulaResponseError):
            await client.get_presence_templates(
                [10],
                date(2026, 2, 25),
                date(2026, 2, 25),
            )

    @pytest.mark.asyncio
    async def test_get_presence_templates_string_data_raises(self, client, http):
        http.aula(TEMPLATES, ok("string instead of dict"))

        with pytest.raises(AulaResponseError):
            await client.get_presence_templates(
                [10],
                date(2026, 2, 25),
                date(2026, 2, 25),
            )

    @pytest.mark.asyncio
    async def test_get_presence_templates_non_dict_items(self, client, http):
        """Test handling when list contains non-dict items."""
        data = {
            "presenceWeekTemplates": [
                {
                    "institutionProfile": {"id": 10},
                    "dayTemplates": [{"id": 1}],
                },
                "not a dict",
                123,
                {
                    "institutionProfile": {"id": 20},
                    "dayTemplates": [{"id": 2}],
                },
            ]
        }

        http.aula(TEMPLATES, ok(data))

        result = await client.get_presence_templates(
            [10, 20],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        # Should skip non-dict items and return 2 valid templates
        assert len(result) == 2


class TestPaginationSafetyGuards:
    """Tests for MAX_PAGES safety guards in pagination methods."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_get_all_message_threads_stops_repeated_pages_within_max_pages(self, client):
        """get_all_message_threads stops at MAX_PAGES."""
        # Return threads with recent dates so cutoff never triggers
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"threads": [thread_item("t1", "2026-12-01T00:00:00+01:00")]}},
            )
        )

        with patch("aula.api_client.MAX_PAGES", 3):
            result = await client.get_all_message_threads(date(2020, 1, 1))

        assert client._request_with_version_retry.call_count == 2
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_all_messages_for_thread_stops_repeated_pages_within_max_pages(self, client):
        """get_all_messages_for_thread stops at MAX_PAGES."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"messages": [{"id": "m1", "text": "hello"}]}},
            )
        )

        with patch("aula.api_client.MAX_PAGES", 3):
            result = await client.get_all_messages_for_thread("t1")

        assert client._request_with_version_retry.call_count == 2
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_messages_stops_repeated_pages_within_max_pages(self, client):
        """search_messages stops at MAX_PAGES."""
        # Return results that never exhaust totalSize so pagination continues
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "results": [search_hit({"id": "m1", "text": {"html": "<p>hi</p>"}})],
                        "totalSize": 99999,
                    }
                },
            )
        )

        with patch("aula.api_client.MAX_PAGES", 3):
            result = await client.search_messages(
                institution_profile_ids=[1],
                institution_codes=["INST1"],
                text="test",
                limit=1,
            )

        assert client._request_with_version_retry.call_count == 2
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_all_message_threads_stops_on_empty(self, client):
        """get_all_message_threads stops when no threads returned (before MAX_PAGES)."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                HttpResponse(
                    status_code=200,
                    data={"data": {"threads": [thread_item("t1", "2026-12-01T00:00:00+01:00")]}},
                ),
                HttpResponse(
                    status_code=200,
                    data={"data": {"threads": []}},
                ),
            ]
        )

        result = await client.get_all_message_threads(date(2020, 1, 1))
        assert client._request_with_version_retry.call_count == 2
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_all_messages_for_thread_stops_on_empty(self, client):
        """get_all_messages_for_thread stops when no messages returned."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                HttpResponse(
                    status_code=200,
                    data={"data": {"messages": [{"id": "m1", "text": "hi"}]}},
                ),
                HttpResponse(
                    status_code=200,
                    data={"data": {"messages": []}},
                ),
            ]
        )

        result = await client.get_all_messages_for_thread("t1")
        assert client._request_with_version_retry.call_count == 2
        assert len(result) == 1


class TestWidgetNamespaceSmoke:
    """Smoke check for the transitional widgets namespace."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    def test_client_exposes_widgets_namespace(self, client):
        """AulaApiClient exposes a widgets namespace attribute."""
        assert client.widgets is not None


class TestLegacyWidgetMethodWrappers:
    """Compatibility wrappers delegate to widgets with deprecation warnings."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_get_mu_tasks_delegates_and_warns(self, client):
        expected = [MagicMock()]
        client.widgets.get_mu_tasks = AsyncMock(return_value=expected)

        with pytest.warns(DeprecationWarning, match="get_mu_tasks") as warning_info:
            result = await client.get_mu_tasks(
                widget_id="widget-id",
                child_filter=["child-1"],
                institution_filter=["inst-1"],
                week="2026-W08",
                session_uuid="session-uuid",
            )

        assert result == expected
        client.widgets.get_mu_tasks.assert_awaited_once_with(
            widget_id="widget-id",
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W08",
            session_uuid="session-uuid",
        )
        assert warning_info[0].filename.endswith("test_api_client.py")

    @pytest.mark.asyncio
    async def test_get_library_status_delegates_and_warns(self, client):
        expected = MagicMock()
        client.widgets.get_library_status = AsyncMock(return_value=expected)

        with pytest.warns(DeprecationWarning, match="get_library_status") as warning_info:
            result = await client.get_library_status(
                widget_id="widget-id",
                children=["child-1"],
                institutions=["inst-1"],
                session_uuid="session-uuid",
            )

        assert result == expected
        client.widgets.get_library_status.assert_awaited_once_with(
            widget_id="widget-id",
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-uuid",
        )
        assert warning_info[0].filename.endswith("test_api_client.py")

    @pytest.mark.asyncio
    async def test_get_ugeplan_delegates_and_warns_with_callsite_stacklevel(self, client):
        expected = [MagicMock()]
        client.widgets.get_ugeplan = AsyncMock(return_value=expected)

        with pytest.warns(DeprecationWarning, match="get_ugeplan") as warning_info:
            frame = inspect.currentframe()
            assert frame is not None
            call_line = frame.f_lineno + 1
            result = await client.get_ugeplan(
                widget_id="widget-id",
                child_filter=["child-1"],
                institution_filter=["inst-1"],
                week="2026-W08",
                session_uuid="session-uuid",
            )

        assert result == expected
        client.widgets.get_ugeplan.assert_awaited_once_with(
            widget_id="widget-id",
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W08",
            session_uuid="session-uuid",
        )
        assert warning_info[0].filename.endswith("test_api_client.py")
        assert warning_info[0].lineno == call_line

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_delegates_and_warns_with_callsite_stacklevel(self, client):
        expected = [MagicMock()]
        client.widgets.get_easyiq_weekplan = AsyncMock(return_value=expected)

        with pytest.warns(DeprecationWarning, match="get_easyiq_weekplan") as warning_info:
            frame = inspect.currentframe()
            assert frame is not None
            call_line = frame.f_lineno + 1
            result = await client.get_easyiq_weekplan(
                week="2026-W08",
                session_uuid="session-uuid",
                institution_filter=["inst-1"],
                child_id="child-1",
            )

        assert result == expected
        client.widgets.get_easyiq_weekplan.assert_awaited_once_with(
            week="2026-W08",
            session_uuid="session-uuid",
            institution_filter=["inst-1"],
            child_id="child-1",
        )
        assert warning_info[0].filename.endswith("test_api_client.py")
        assert warning_info[0].lineno == call_line

    @pytest.mark.asyncio
    async def test_get_meebook_weekplan_delegates_and_warns_with_callsite_stacklevel(self, client):
        expected = [MagicMock()]
        client.widgets.get_meebook_weekplan = AsyncMock(return_value=expected)

        with pytest.warns(DeprecationWarning, match="get_meebook_weekplan") as warning_info:
            frame = inspect.currentframe()
            assert frame is not None
            call_line = frame.f_lineno + 1
            result = await client.get_meebook_weekplan(
                child_filter=["child-1"],
                institution_filter=["inst-1"],
                week="2026-W08",
                session_uuid="session-uuid",
            )

        assert result == expected
        client.widgets.get_meebook_weekplan.assert_awaited_once_with(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W08",
            session_uuid="session-uuid",
        )
        assert warning_info[0].filename.endswith("test_api_client.py")
        assert warning_info[0].lineno == call_line

    @pytest.mark.asyncio
    async def test_get_momo_courses_delegates_and_warns_with_callsite_stacklevel(self, client):
        expected = [MagicMock()]
        client.widgets.get_momo_courses = AsyncMock(return_value=expected)

        with pytest.warns(DeprecationWarning, match="get_momo_courses") as warning_info:
            frame = inspect.currentframe()
            assert frame is not None
            call_line = frame.f_lineno + 1
            result = await client.get_momo_courses(
                children=["child-1"],
                institutions=["inst-1"],
                session_uuid="session-uuid",
            )

        assert result == expected
        client.widgets.get_momo_courses.assert_awaited_once_with(
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-uuid",
        )
        assert warning_info[0].filename.endswith("test_api_client.py")
        assert warning_info[0].lineno == call_line


class TestGetWidgetToken:
    @pytest.mark.asyncio
    async def test_returns_the_raw_token_from_get_aula_token(self):
        http = FakeHttpClient()
        client = AulaApiClient(http)
        http.route(
            f"{client.api_url}?method=aulaToken.getAulaToken",
            HttpResponse(200, {"status": {"code": 0}, "data": "token-123"}),
        )

        assert await client.get_widget_token("0030") == "token-123"
        assert [request.url for request in http.requests] == [
            f"{client.api_url}?method=aulaToken.getAulaToken&widgetId=0030"
        ]
        assert client.http_client is http

    @pytest.mark.asyncio
    async def test_a_refused_mint_is_an_aula_authentication_error(self):
        http = FakeHttpClient()
        client = AulaApiClient(http)
        http.route(f"{client.api_url}?method=aulaToken.getAulaToken", HttpResponse(403, None))

        with pytest.raises(AulaAuthenticationError):
            await client.get_widget_token("0030")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [{}, {"data": None}, {"data": ""}, None, ["token-123"]])
    async def test_an_answer_without_a_token_is_an_aula_response_error(self, body):
        http = FakeHttpClient()
        client = AulaApiClient(http)
        http.route(f"{client.api_url}?method=aulaToken.getAulaToken", HttpResponse(200, body))

        with pytest.raises(AulaResponseError) as exc_info:
            await client.get_widget_token("0030")
        assert exc_info.value.status_code == 200


def client_answering(response):
    """A client whose every request gets ``response``."""
    client = AulaApiClient(AsyncMock(), access_token="test_token")
    client._request_with_version_retry = AsyncMock(return_value=response)
    return client


LIST_READS = {
    "get_pickup_responsibles": lambda c: c.get_pickup_responsibles([1000001]),
    "get_presence_registrations": lambda c: c.get_presence_registrations(
        [1000001], date.today(), date.today()
    ),
    "get_presence_states": lambda c: c.get_presence_states(),
    "get_presence_configuration": lambda c: c.get_presence_configuration([1000001]),
    "get_notifications_for_active_profile": lambda c: c.get_notifications_for_active_profile(),
    "get_calendar_events": lambda c: c.get_calendar_events(
        [1000001], datetime.now(), datetime.now()
    ),
    "get_important_dates": lambda c: c.get_important_dates(),
    "get_birthday_events": lambda c: c.get_birthday_events(["G90001"], "2026-01-01", "2026-01-02"),
    "get_birthday_events_for_group": lambda c: c.get_birthday_events_for_group(
        1000001, "2026-01-01", "2026-01-02"
    ),
    "get_event_types": lambda c: c.get_event_types(),
    "get_daily_aggregated_events": lambda c: c.get_daily_aggregated_events(
        [1000001], "2026-01-01", "2026-01-02"
    ),
    "get_events_for_institutions": lambda c: c.get_events_for_institutions(
        ["G90001"], "2026-01-01", "2026-01-02"
    ),
    "get_daily_event_count_for_group": lambda c: c.get_daily_event_count_for_group(
        1000001, "2026-01-01", "2026-01-02"
    ),
    "get_events_by_group": lambda c: c.get_events_by_group(1000001, "2026-01-01", "2026-01-02"),
    "get_groups": lambda c: c.get_groups(child_institution_profile_ids=[1000001]),
    "get_group_members": lambda c: c.get_group_members(1000001),
    "get_comments": lambda c: c.get_comments("post", 1000001),
    "get_gallery_albums": lambda c: c.get_gallery_albums([1000001]),
    "get_album_pictures": lambda c: c.get_album_pictures([1000001], 1000001),
    "get_message_folders": lambda c: c.get_message_folders(),
    "get_common_inboxes": lambda c: c.get_common_inboxes(),
    "get_threads_in_bundle": lambda c: c.get_threads_in_bundle(1000001),
    "get_contact_list": lambda c: c.get_contact_list(1000001),
    "get_contact_parents": lambda c: c.get_contact_parents(),
    "get_media_by_profile": lambda c: c.get_media_by_profile(1000001),
    "get_consent_responses": lambda c: c.get_consent_responses([1000001]),
    "get_vacation_registrations": lambda c: c.get_vacation_registrations([1000001]),
    "get_notification_settings": lambda c: c.get_notification_settings(),
}

OBJECT_READS = {
    "get_presence_templates": lambda c: c.get_presence_templates(
        [1000001], date.today(), date.today()
    ),
    "get_presence_registration_detail": lambda c: c.get_presence_registration_detail(1000001),
    "get_activity_overview": lambda c: c.get_activity_overview([1000001], 1, 2026),
    "get_message_threads": lambda c: c.get_message_threads(),
    "get_messages_for_thread": lambda c: c.get_messages_for_thread("1000001"),
    "get_calendar_event": lambda c: c.get_calendar_event(1000001),
    "get_group": lambda c: c.get_group(1000001),
    "get_posts": lambda c: c.get_posts([1000001]),
    "get_post": lambda c: c.get_post(1000001),
    "get_message_info": lambda c: c.get_message_info("1000001", "1000001"),
    "find_recipients": lambda c: c.find_recipients("Barn"),
    "find_profiles_and_groups": lambda c: c.find_profiles_and_groups("Barn"),
    "search": lambda c: c.search("Barn"),
    "get_media_by_id": lambda c: c.get_media_by_id(1000001),
    "get_profile_master_data": lambda c: c.get_profile_master_data(1000001),
    "get_auto_reply": lambda c: c.get_auto_reply(),
    "search_groups": lambda c: c.search_groups("Barn"),
    "get_secure_documents": lambda c: c.get_secure_documents([1000001]),
    "get_common_files": lambda c: c.get_common_files(["G90001"]),
}

NESTED_LIST_READS = [
    pytest.param(lambda c: c.get_profile(), {"profiles": "profile"}, id="get_profile"),
    pytest.param(
        lambda c: c.get_widgets(),
        {"pageConfiguration": {"widgetConfigurations": "widget"}},
        id="get_widgets",
    ),
    pytest.param(
        OBJECT_READS["get_presence_templates"],
        {"presenceWeekTemplates": "template"},
        id="get_presence_templates",
    ),
    pytest.param(OBJECT_READS["get_message_threads"], {"threads": "t1"}, id="get_message_threads"),
    pytest.param(
        OBJECT_READS["get_messages_for_thread"], {"messages": "m1"}, id="get_messages_for_thread"
    ),
    pytest.param(OBJECT_READS["get_posts"], {"posts": "post"}, id="get_posts"),
    pytest.param(OBJECT_READS["find_recipients"], {"results": "hit"}, id="find_recipients"),
    pytest.param(OBJECT_READS["search_groups"], {"results": "hit"}, id="search_groups"),
    pytest.param(
        OBJECT_READS["get_secure_documents"], {"documents": "doc"}, id="get_secure_documents"
    ),
    pytest.param(OBJECT_READS["get_common_files"], {"commonFiles": "file"}, id="get_common_files"),
    pytest.param(LIST_READS["get_gallery_albums"], {"albums": "album"}, id="get_gallery_albums"),
    pytest.param(LIST_READS["get_album_pictures"], {"results": "picture"}, id="get_album_pictures"),
    pytest.param(
        lambda c: c.search_messages_result([1000001], ["G90001"]),
        {"results": "hit"},
        id="search_messages_result",
    ),
    pytest.param(
        lambda c: c.get_all_message_threads_result(date.today()),
        {"threads": "t1"},
        id="get_all_message_threads_result",
    ),
    pytest.param(
        lambda c: c.get_all_messages_for_thread_result("1000001"),
        {"messages": "m1"},
        id="get_all_messages_for_thread_result",
    ),
]


class TestAnswerThatIsNotAJsonObject:
    """A body that is not a JSON object raises AulaResponseError on every read."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "call",
        [*LIST_READS.values(), *OBJECT_READS.values()],
        ids=[*LIST_READS, *OBJECT_READS],
    )
    @pytest.mark.parametrize("body", [None, ["data"]])
    async def test_is_an_aula_response_error(self, call, body):
        with pytest.raises(AulaResponseError):
            await call(client_answering(HttpResponse(status_code=200, data=body)))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "call",
        [
            lambda c: c.get_message_folders(),
            lambda c: c.get_group(1000001),
            lambda c: c.get_profile_context(),
            lambda c: c.get_widget_token("0030"),
        ],
    )
    async def test_a_body_that_is_not_json_is_an_aula_response_error(self, call):
        class HtmlResponse(HttpResponse):
            def json(self):
                raise ValueError("not JSON")

        with pytest.raises(AulaResponseError) as exc_info:
            await call(client_answering(HtmlResponse(status_code=200)))
        assert isinstance(exc_info.value.__cause__, ValueError)


class TestDataThatIsNotTheExpectedObject:
    """Data of the wrong type raises AulaResponseError; null data is empty."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "call",
        [*LIST_READS.values(), lambda c: c.get_daily_overview(1000001)],
        ids=[*LIST_READS, "get_daily_overview"],
    )
    @pytest.mark.parametrize("data", ["data", 1000001])
    async def test_a_list_read_is_an_aula_response_error(self, call, data):
        with pytest.raises(AulaResponseError):
            await call(client_answering(HttpResponse(status_code=200, data={"data": data})))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", LIST_READS.values(), ids=LIST_READS.keys())
    @pytest.mark.parametrize("body", [{}, {"data": None}])
    async def test_a_list_read_of_null_data_returns_nothing(self, call, body):
        assert await call(client_answering(HttpResponse(status_code=200, data=body))) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", OBJECT_READS.values(), ids=OBJECT_READS.keys())
    @pytest.mark.parametrize("data", ["data", ["data"]])
    async def test_an_object_read_is_an_aula_response_error(self, call, data):
        with pytest.raises(AulaResponseError):
            await call(client_answering(HttpResponse(status_code=200, data={"data": data})))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", OBJECT_READS.values(), ids=OBJECT_READS.keys())
    @pytest.mark.parametrize("body", [{}, {"data": None}, {"data": []}])
    async def test_an_object_read_of_null_data_returns_nothing(self, call, body):
        assert not await call(client_answering(HttpResponse(status_code=200, data=body)))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("call", "data"), NESTED_LIST_READS)
    async def test_a_list_inside_data_that_is_not_a_list_is_an_aula_response_error(
        self, call, data
    ):
        with pytest.raises(AulaResponseError):
            await call(client_answering(HttpResponse(status_code=200, data={"data": data})))


def _groups(*records):
    return HttpResponse(200, {"data": {"results": list(records)}})


GOOD_GROUP = {"id": 1, "name": "Skole Et 3.A"}
BAD_GROUP = {"id": "not-a-number"}


def _parse_loop(name, call, target, wrap):
    """A parse loop, the parser it calls, and how its answer wraps a list of records."""
    return pytest.param(call, target, wrap, id=name)


EVERY_PARSE_LOOP = [
    _parse_loop(
        "get_profile",
        lambda c: c.get_profile(),
        "Child.from_dict",
        lambda records: {"data": {"profiles": [{"profileId": 1, "children": records}]}},
    ),
    _parse_loop(
        "get_widgets",
        lambda c: c.get_widgets(),
        "WidgetConfiguration.from_dict",
        lambda records: {"data": {"pageConfiguration": {"widgetConfigurations": records}}},
    ),
    _parse_loop(
        "get_presence_templates",
        lambda c: c.get_presence_templates([1000001], date.today(), date.today()),
        "PresenceWeekTemplate.from_dict",
        lambda records: {"data": {"presenceWeekTemplates": records}},
    ),
    _parse_loop(
        "get_pickup_responsibles",
        lambda c: c.get_pickup_responsibles([1000001]),
        "ChildPickupResponsibles.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "get_presence_registrations",
        lambda c: c.get_presence_registrations([1000001], date.today(), date.today()),
        "PresenceRegistration.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "get_presence_states",
        lambda c: c.get_presence_states(),
        "ChildPresenceState.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "get_presence_configuration",
        lambda c: c.get_presence_configuration([1000001]),
        "PresenceConfiguration.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "get_notifications_for_active_profile",
        lambda c: c.get_notifications_for_active_profile(),
        "Notification.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "get_message_threads",
        lambda c: c.get_message_threads(),
        "MessageThread.from_dict",
        lambda records: {"data": {"threads": records}},
    ),
    _parse_loop(
        "get_messages_for_thread",
        lambda c: c.get_messages_for_thread("1000001"),
        "Message.from_dict",
        lambda records: {"data": {"messages": records}},
    ),
    _parse_loop(
        "get_calendar_events",
        lambda c: c.get_calendar_events([1000001], datetime.now(), datetime.now()),
        "CalendarEvent",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "get_groups",
        lambda c: c.get_groups(institution_codes=["G90001"]),
        "Group.from_dict",
        lambda records: {"data": {"groups": records}},
    ),
    _parse_loop(
        "get_group_members",
        lambda c: c.get_group_members(1000001),
        "GroupMember.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "get_posts",
        lambda c: c.get_posts([1000001]),
        "Post.from_dict",
        lambda records: {"data": {"posts": records}},
    ),
    _parse_loop(
        "get_comments",
        lambda c: c.get_comments("post", 1),
        "Comment.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "search_messages_result",
        lambda c: c.search_messages_result([1000001], ["G90001"]),
        "Message.from_search_hit",
        lambda records: {"data": {"results": records}},
    ),
    _parse_loop(
        "get_message_folders",
        lambda c: c.get_message_folders(),
        "MessageFolder.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "get_threads_in_bundle",
        lambda c: c.get_threads_in_bundle(1000001),
        "MessageThread.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "get_consent_responses",
        lambda c: c.get_consent_responses([1000001]),
        "ConsentResponse.from_dict",
        lambda records: {"data": records},
    ),
    _parse_loop(
        "search_groups",
        lambda c: c.search_groups("3.A"),
        "Group.from_dict",
        lambda records: {"data": {"results": records}},
    ),
    _parse_loop(
        "get_secure_documents",
        lambda c: c.get_secure_documents([1000001]),
        "SecureDocument.from_dict",
        lambda records: {"data": {"documents": records, "moreDocumentsExists": False}},
    ),
    _parse_loop(
        "get_common_files",
        lambda c: c.get_common_files(["G90001"]),
        "CommonFile.from_dict",
        lambda records: {"data": {"commonFiles": records, "totalAmount": len(records)}},
    ),
    _parse_loop(
        "get_vacation_registrations",
        lambda c: c.get_vacation_registrations([1000001]),
        "VacationRegistration.from_dict",
        lambda records: {"data": [{"child": {}, "vacationRegistrations": records}]},
    ),
    _parse_loop(
        "get_notification_settings",
        lambda c: c.get_notification_settings(),
        "NotificationSetting.from_dict",
        lambda records: {"data": records},
    ),
]

RECORD_THAT_REACHES_THE_PARSER = {
    "id": 1,
    "title": "Opslag",
    "institutionProfileId": 1000001,
    "messageType": "Message",
    "startDateTime": "2026-11-23T08:00:00+01:00",
    "endDateTime": "2026-11-23T09:00:00+01:00",
}


class TestRecordsThatFailToParse:
    @pytest.mark.asyncio
    async def test_all_records_failing_is_an_aula_response_error(self):
        http = FakeHttpClient()
        http.route(API_URL, _groups(BAD_GROUP, BAD_GROUP, BAD_GROUP))

        with pytest.raises(AulaResponseError) as exc_info:
            await AulaApiClient(http).search_groups("3.A")

        assert exc_info.value.status_code == 200
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert "3 group search result records" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_the_error_holds_no_record_values(self):
        http = FakeHttpClient()
        http.route(API_URL, _groups({"id": "Barn Et"}))

        with pytest.raises(AulaResponseError) as exc_info:
            await AulaApiClient(http).search_groups("3.A")

        assert "Barn Et" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_the_warning_holds_no_record_values(self, caplog):
        http = FakeHttpClient()
        http.route(API_URL, _groups(GOOD_GROUP, {"id": "Barn Et"}))

        with caplog.at_level(logging.WARNING, logger="aula"):
            await AulaApiClient(http).search_groups("3.A")

        assert "Skipping group search result: ValueError" in caplog.text
        assert "Barn Et" not in caplog.text

    @pytest.mark.asyncio
    async def test_some_records_failing_are_skipped_with_a_warning(self, caplog):
        http = FakeHttpClient()
        http.route(API_URL, _groups(GOOD_GROUP, BAD_GROUP, GOOD_GROUP))

        with caplog.at_level(logging.WARNING, logger="aula"):
            groups = await AulaApiClient(http).search_groups("3.A")

        assert [group.id for group in groups] == [1, 1]
        assert "Skipping group search result: ValueError" in caplog.text
        assert "keys: id" in caplog.text

    @pytest.mark.asyncio
    async def test_an_empty_answer_is_an_empty_list(self):
        http = FakeHttpClient()
        http.route(API_URL, _groups())

        assert await AulaApiClient(http).search_groups("3.A") == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("call", "target", "wrap"), EVERY_PARSE_LOOP)
    async def test_every_parse_loop_raises_when_nothing_parses(self, call, target, wrap, caplog):
        records = [{**RECORD_THAT_REACHES_THE_PARSER, "id": n} for n in (1, 2, 3)]
        client = client_answering(HttpResponse(200, wrap(records)))

        with (
            caplog.at_level(logging.WARNING, logger="aula"),
            patch(f"aula.api_client.{target}", side_effect=ValueError("bad record")),
            pytest.raises(AulaResponseError) as exc_info,
        ):
            await call(client)

        assert str(exc_info.value.__cause__) == "bad record"
        assert "any of the 3 " in str(exc_info.value)
        assert caplog.text.count("Skipping ") == 3
        assert "Opslag" not in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("call", "target", "wrap"), EVERY_PARSE_LOOP)
    async def test_every_parse_loop_raises_when_no_record_is_an_object(self, call, target, wrap):
        client = client_answering(HttpResponse(200, wrap(["record", 1000001])))

        with pytest.raises(AulaResponseError) as exc_info:
            await call(client)

        assert isinstance(exc_info.value.__cause__, TypeError)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("call", "target", "wrap"), EVERY_PARSE_LOOP)
    async def test_every_parse_loop_skips_a_failed_record_when_another_parses(
        self, call, target, wrap, caplog
    ):
        records = [RECORD_THAT_REACHES_THE_PARSER, {**RECORD_THAT_REACHES_THE_PARSER, "id": 2}]
        client = client_answering(HttpResponse(200, wrap(records)))
        parsed = MagicMock(aggregated_display_mode="Shown", start_datetime=datetime.now())

        with (
            caplog.at_level(logging.WARNING, logger="aula"),
            patch(f"aula.api_client.{target}", side_effect=[ValueError("bad record"), parsed]),
            patch("aula.api_client.merge_duplicate_lessons", side_effect=lambda events: events),
        ):
            await call(client)

        assert caplog.text.count("Skipping ") == 1


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_refuses_a_file_larger_than_max_bytes(self):
        http = HttpxHttpClient(
            httpx_client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, content=b"9 bytes!!")
                )
            )
        )

        with pytest.raises(DownloadTooLargeError):
            await AulaApiClient(http).download_file("https://media.aula.dk/file.pdf", max_bytes=8)


class TestGetCalendarEvents:
    """Tests for AulaApiClient.get_calendar_events method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        c = AulaApiClient(http_client=http_client, access_token="test_token")
        c._access_token = None
        c._csrf_token = "csrf"
        return c

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("start", "end"),
        [
            (datetime(2026, 3, 2), datetime(2026, 3, 1)),
            (
                datetime(2026, 3, 2, tzinfo=timezone(timedelta(hours=14))),
                datetime(2026, 3, 1, tzinfo=timezone(timedelta(hours=-12))),
            ),
        ],
        ids=["naive", "local-dates-reversed-despite-ordered-instants"],
    )
    async def test_reversed_dates_raise_before_http_request(self, start, end):
        http_client = AsyncMock()
        http_client.request.return_value = HttpResponse(status_code=200, data={"data": []})
        client = AulaApiClient(http_client=http_client, access_token="test_token")

        with pytest.raises(ValueError, match="start date.*end date"):
            await client.get_calendar_events([100], start, end)

        http_client.request.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("start", "end", "expected_start", "expected_end"),
        [
            (
                "2026-03-01T12:30:00",
                "2026-03-02T09:15:00",
                "2026-03-01 00:00:00.0000",
                "2026-03-02 23:59:59.0000",
            ),
            (
                "2026-03-01T09:00:00+01:00",
                "2026-03-01T17:00:00+01:00",
                "2026-03-01 00:00:00.0000+0100",
                "2026-03-01 23:59:59.0000+0100",
            ),
            (
                "2026-03-01T23:00:00",
                "2026-03-01T01:00:00",
                "2026-03-01 00:00:00.0000",
                "2026-03-01 23:59:59.0000",
            ),
            (
                "2026-03-01T23:00:00-12:00",
                "2026-03-02T00:00:00+14:00",
                "2026-03-01 00:00:00.0000-1200",
                "2026-03-02 23:59:59.0000+1400",
            ),
            (
                "2026-03-01T23:00:00+01:00",
                "2026-03-01T01:00:00",
                "2026-03-01 00:00:00.0000+0100",
                "2026-03-01 23:59:59.0000",
            ),
        ],
        ids=[
            "ordered-naive",
            "same-day-aware",
            "same-day-reversed-times",
            "ordered-local-dates-despite-reversed-instants",
            "mixed-awareness",
        ],
    )
    async def test_valid_dates_preserve_whole_day_request_and_parse_events(
        self, start, end, expected_start, expected_end
    ):
        http_client = AsyncMock()
        http_client.request.return_value = HttpResponse(
            status_code=200,
            data={
                "data": [
                    {
                        "id": 1,
                        "title": "Math",
                        "startDateTime": "2026-03-01T08:00:00+01:00",
                        "endDateTime": "2026-03-01T09:00:00+01:00",
                        "belongsToProfiles": [100],
                    }
                ]
            },
        )
        client = AulaApiClient(http_client=http_client, access_token="test_token")

        events = await client.get_calendar_events(
            [100], datetime.fromisoformat(start), datetime.fromisoformat(end)
        )

        assert len(events) == 1
        assert events[0].id == 1
        assert events[0].title == "Math"
        http_client.request.assert_awaited_once()
        assert http_client.request.call_args.kwargs["json"] == {
            "instProfileIds": [100],
            "resourceIds": [],
            "start": expected_start,
            "end": expected_end,
        }

    @pytest.mark.asyncio
    async def test_happy_path_with_lesson(self, client):
        """Events with lesson participants are parsed correctly."""
        raw_events = [
            {
                "id": 1,
                "title": "Math",
                "startDateTime": "2026-03-01T08:00:00+01:00",
                "endDateTime": "2026-03-01T09:00:00+01:00",
                "belongsToProfiles": [100],
                "primaryResource": {"name": "Room 101"},
                "lesson": {
                    "participants": [
                        {"participantRole": "primaryTeacher", "teacherName": "Lærer Et"},
                        {"participantRole": "substituteTeacher", "teacherName": "Lærer To"},
                    ],
                    "lessonStatus": "substitute",
                },
            }
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": raw_events})
        )

        events = await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1))

        assert len(events) == 1
        assert events[0].title == "Math"
        assert events[0].teacher_name == "Lærer Et"
        assert events[0].has_substitute is True
        assert events[0].substitute_name == "Lærer To"
        assert events[0].location == "Room 101"
        assert events[0].belongs_to == 100

    @pytest.mark.asyncio
    async def test_empty_events_list(self, client):
        """Empty events list returns empty."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        events = await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1))
        assert events == []

    @pytest.mark.asyncio
    async def test_event_with_no_lesson(self, client):
        """Event with no lesson data uses graceful defaults."""
        raw_events = [
            {
                "id": 2,
                "title": "Parent Meeting",
                "startDateTime": "2026-03-02T14:00:00+01:00",
                "endDateTime": "2026-03-02T15:00:00+01:00",
                "belongsToProfiles": [],
                "lesson": None,
            }
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": raw_events})
        )

        events = await client.get_calendar_events([100], datetime(2026, 3, 2), datetime(2026, 3, 2))

        assert len(events) == 1
        assert events[0].teacher_name == ""
        assert events[0].has_substitute is False
        assert events[0].location is None

    @pytest.mark.asyncio
    async def test_malformed_event_skipped(self, client, caplog):
        """Malformed event is skipped and logged."""
        raw_events = [
            {"id": 1, "title": "Bad", "startDateTime": "not-a-date"},
            {
                "id": 2,
                "title": "Good",
                "startDateTime": "2026-03-01T08:00:00+01:00",
                "endDateTime": "2026-03-01T09:00:00+01:00",
                "belongsToProfiles": [],
            },
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": raw_events})
        )

        events = await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1))
        assert len(events) == 1
        assert events[0].title == "Good"

    @pytest.mark.asyncio
    async def test_non_list_data_raises(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": "unexpected"})
        )
        with pytest.raises(AulaResponseError):
            await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1))

    @pytest.mark.asyncio
    async def test_null_data_returns_empty(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": None})
        )
        events = await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1))
        assert events == []

    @pytest.mark.asyncio
    async def test_co_taught_lesson_returned_once(self, client):
        """Aula's one-row-per-adult duplicates collapse to one event."""
        raw_events = [
            {
                "id": "3120da43",
                "title": "DFA 2",
                "startDateTime": "2026-09-14T08:15:00+01:00",
                "endDateTime": "2026-09-14T09:00:00+01:00",
                "belongsToProfiles": [100],
                "primaryResource": {"name": "Room 101"},
                "lesson": {
                    "participants": [
                        {"participantRole": "primaryTeacher", "teacherName": "Laerer 1"},
                    ],
                },
            },
            {
                "id": "eb86b3c9",
                "title": "DFA 2",
                "startDateTime": "2026-09-14T08:15:00+01:00",
                "endDateTime": "2026-09-14T09:00:00+01:00",
                "belongsToProfiles": [100],
                "primaryResource": {"name": "Room 101"},
                "lesson": {
                    "participants": [
                        {"participantRole": "primaryTeacher", "teacherName": "Laerer 2"},
                    ],
                },
            },
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": raw_events})
        )

        events = await client.get_calendar_events(
            [100], datetime(2026, 9, 14), datetime(2026, 9, 14)
        )

        assert len(events) == 1
        assert events[0].teacher_names == ["Laerer 1", "Laerer 2"]

    @pytest.mark.asyncio
    async def test_multiple_teachers_on_one_row(self, client):
        """Several primary teachers inside a single row are all read."""
        raw_events = [
            {
                "id": 1,
                "title": "Math",
                "startDateTime": "2026-03-01T08:00:00+01:00",
                "endDateTime": "2026-03-01T09:00:00+01:00",
                "belongsToProfiles": [100],
                "lesson": {
                    "participants": [
                        {"participantRole": "primaryTeacher", "teacherName": "Lærer Et"},
                        {"participantRole": "primaryTeacher", "teacherName": "Lærer To"},
                    ],
                },
            }
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": raw_events})
        )

        events = await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1))

        assert len(events) == 1
        assert events[0].teacher_names == ["Lærer Et", "Lærer To"]
        assert events[0].teacher_name == "Lærer Et"

    @pytest.mark.asyncio
    async def test_shared_event_keeps_every_profile_and_its_type(self, client):
        """A lesson twins share names both children, not just the first."""
        raw_events = [
            {
                "id": 1,
                "title": "Math",
                "type": "lesson",
                "startDateTime": "2026-03-01T08:00:00+01:00",
                "endDateTime": "2026-03-01T09:00:00+01:00",
                "belongsToProfiles": [100, 200],
            }
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": raw_events})
        )

        events = await client.get_calendar_events(
            [100, 200], datetime(2026, 3, 1), datetime(2026, 3, 1)
        )

        assert events[0].belongs_to_profiles == [100, 200]
        assert events[0].belongs_to == 100
        assert events[0].event_type == "lesson"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("profiles", [None, "100", [None, "100"]])
    async def test_unusable_profiles_keep_the_event_unowned(self, client, profiles):
        """An event whose profiles cannot be read is kept, belonging to no one."""
        raw_events = [
            {
                "id": 1,
                "title": "Math",
                "startDateTime": "2026-03-01T08:00:00+01:00",
                "endDateTime": "2026-03-01T09:00:00+01:00",
                "belongsToProfiles": profiles,
            }
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": raw_events})
        )

        events = await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1))

        assert len(events) == 1
        assert events[0].belongs_to_profiles == []
        assert events[0].belongs_to is None
        assert events[0].event_type is None


class TestGetCalendarEventsByChild:
    """Tests for AulaApiClient.get_calendar_events_by_child."""

    START = datetime(2026, 3, 2, 10, 30, tzinfo=UTC)
    END = datetime(2026, 3, 6, 18, 0, tzinfo=UTC)

    @staticmethod
    def _row(event_id, title, profiles, event_type="lesson"):
        return {
            "id": event_id,
            "title": title,
            "type": event_type,
            "startDateTime": "2026-03-02T08:00:00+01:00",
            "endDateTime": "2026-03-02T09:00:00+01:00",
            "belongsToProfiles": profiles,
        }

    @pytest.fixture
    def client(self):
        c = AulaApiClient(http_client=AsyncMock(), access_token="test_token")
        c._request_with_version_retry = AsyncMock()
        c.get_meeting_bookings = AsyncMock(return_value=[])
        return c

    def _answer(self, client, rows):
        client._request_with_version_retry.return_value = HttpResponse(
            status_code=200, data={"status": {"code": 0}, "data": rows}
        )

    @pytest.mark.asyncio
    async def test_shared_event_is_listed_under_every_child_it_names(self, client):
        """Twins in one class both get the shared lesson."""
        self._answer(
            client,
            [
                self._row(1, "Math", [100, 200]),
                self._row(2, "Music", [200]),
                self._row(3, "Other family", [300]),
            ],
        )

        calendars = await client.get_calendar_events_by_child([100, 200], self.START, self.END)

        assert {child: [e.id for e in events] for child, events in calendars.items()} == {
            100: [1],
            200: [1, 2],
        }
        # One calendar request covers both children.
        client._request_with_version_retry.assert_awaited_once()
        assert client._request_with_version_retry.call_args.kwargs["json"]["instProfileIds"] == [
            100,
            200,
        ]

    @pytest.mark.asyncio
    async def test_every_requested_child_has_a_list(self, client):
        self._answer(client, [])

        assert await client.get_calendar_events_by_child([100, 200], self.START, self.END) == {
            100: [],
            200: [],
        }

    @pytest.mark.asyncio
    async def test_no_meeting_in_range_makes_no_booking_requests(self, client):
        self._answer(client, [self._row(1, "Math", [100])])

        await client.get_calendar_events_by_child([100, 200], self.START, self.END)

        client.get_meeting_bookings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_meeting_reads_each_childs_bookings_over_the_same_whole_days(self, client):
        self._answer(client, [self._row(42, "Samtale", [100], "school_home_meeting")])

        await client.get_calendar_events_by_child([100, 200], self.START, self.END)

        calls = client.get_meeting_bookings.await_args_list
        assert [call.args[0] for call in calls] == [100, 200]
        _, start, end = calls[0].args
        assert start == datetime(2026, 3, 2, tzinfo=UTC)
        assert end == datetime(2026, 3, 7, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_failed_booking_read_keeps_that_childs_calendar(self, client, caplog):
        meeting = self._row(42, "Samtale", [100], "school_home_meeting")
        self._answer(client, [meeting])
        client.get_meeting_bookings.side_effect = AulaServerError("Server error", 500)

        with caplog.at_level(logging.WARNING, logger="aula.api_client"):
            calendars = await client.get_calendar_events_by_child([100], self.START, self.END)

        assert [(e.id, e.event_type) for e in calendars[100]] == [(42, "school_home_meeting")]
        assert "Could not fetch booked meetings for child 100" in caplog.text

    @pytest.mark.asyncio
    async def test_auth_error_on_booking_read_raises(self, client):
        self._answer(client, [self._row(42, "Samtale", [100], "school_home_meeting")])
        client.get_meeting_bookings.side_effect = AulaSessionExpiredError("expired", 401)

        with pytest.raises(AulaSessionExpiredError):
            await client.get_calendar_events_by_child([100], self.START, self.END)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("start", "end"),
        [
            (datetime(2026, 3, 2), END),
            (START, datetime(2026, 3, 6)),
            (END, START),
        ],
        ids=["naive-start", "naive-end", "reversed"],
    )
    async def test_invalid_bounds_make_no_requests(self, client, start, end):
        with pytest.raises(ValueError):
            await client.get_calendar_events_by_child([100], start, end)
        client._request_with_version_retry.assert_not_awaited()


class TestGetPosts:
    """Tests for AulaApiClient.get_posts method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        c = AulaApiClient(http_client=http_client, access_token="test_token")
        return c

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        """Posts with id and title are parsed via Post.from_dict."""
        posts_data = [
            {
                "id": 10,
                "title": "School Trip",
                "content": {"html": "<p>Details</p>"},
                "timestamp": "2026-03-01T10:00:00+01:00",
                "ownerProfile": {"id": 1, "profileId": 2},
                "attachments": [],
            }
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": {"posts": posts_data}})
        )
        posts = await client.get_posts([100])
        assert len(posts) == 1
        assert posts[0].id == 10
        assert posts[0].title == "School Trip"

    @pytest.mark.asyncio
    async def test_posts_missing_required_fields_skipped(self, client):
        """Posts without id or title are skipped."""
        posts_data = [
            {"title": "No ID"},
            {"id": 10},
            {
                "id": 20,
                "title": "Valid",
                "content": {"html": ""},
                "ownerProfile": {"id": 1, "profileId": 2},
                "attachments": [],
            },
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": {"posts": posts_data}})
        )
        posts = await client.get_posts([100])
        assert len(posts) == 1
        assert posts[0].id == 20

    @pytest.mark.asyncio
    async def test_non_dict_post_data_skipped(self, client):
        """Non-dict entries in posts list are skipped."""
        posts_data = [
            "not a dict",
            {
                "id": 30,
                "title": "Valid Post",
                "content": {"html": ""},
                "ownerProfile": {"id": 1, "profileId": 2},
                "attachments": [],
            },
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": {"posts": posts_data}})
        )
        posts = await client.get_posts([100])
        assert len(posts) == 1
        assert posts[0].id == 30

    @pytest.mark.asyncio
    async def test_empty_posts(self, client):
        """Empty posts list returns empty."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": {"posts": []}})
        )
        posts = await client.get_posts([100])
        assert posts == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("page", "limit", "index"), [(1, 10, 0), (2, 5, 5), (3, 10, 20)])
    async def test_page_is_sent_as_item_offset(self, client, page, limit, index):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": {"posts": []}})
        )
        await client.get_posts([100], page=page, limit=limit)
        params = client._request_with_version_retry.call_args.kwargs["params"]
        assert params["index"] == index
        assert params["limit"] == limit


class TestGetNotificationsForActiveProfile:
    """Tests for AulaApiClient.get_notifications_for_active_profile method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        """Valid notification list is parsed."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": [
                        {
                            "id": 1,
                            "title": "Ny besked",
                            "module": "messaging",
                            "createdAt": "2026-02-27T10:00:00",
                        }
                    ]
                },
            )
        )

        items = await client.get_notifications_for_active_profile(offset=5, limit=10)

        assert len(items) == 1
        assert items[0].id == "1"
        assert items[0].title == "Ny besked"
        assert items[0].module == "messaging"

        _, kwargs = client._request_with_version_retry.call_args
        assert kwargs["params"]["method"] == "notifications.getNotificationsForActiveProfile"
        assert kwargs["params"]["offset"] == 5
        assert kwargs["params"]["limit"] == 10

    @pytest.mark.asyncio
    async def test_children_and_institution_codes_forwarded(self, client):
        """Children IDs and institution codes are included in query params."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )

        await client.get_notifications_for_active_profile(
            children_ids=[111, 222],
            institution_codes=["G90001", "900001"],
        )

        _, kwargs = client._request_with_version_retry.call_args
        assert kwargs["params"]["activeChildrenIds[]"] == [111, 222]
        assert kwargs["params"]["activeInstitutionCodes[]"] == ["G90001", "900001"]

    @pytest.mark.asyncio
    async def test_module_filter_is_forwarded(self, client):
        """Optional module filter is included in query params."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )

        await client.get_notifications_for_active_profile(module="messaging")

        _, kwargs = client._request_with_version_retry.call_args
        assert kwargs["params"]["module"] == "messaging"

    @pytest.mark.asyncio
    async def test_non_list_data_raises(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": {"results": []}})
        )

        with pytest.raises(AulaResponseError):
            await client.get_notifications_for_active_profile()

    @pytest.mark.asyncio
    async def test_malformed_items_are_skipped(self, client):
        """Malformed entries are skipped while valid ones are returned."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": ["bad", {"id": 2, "heading": "Fallback title"}]},
            )
        )

        items = await client.get_notifications_for_active_profile()
        assert len(items) == 1
        assert items[0].id == "2"
        assert items[0].title == "Fallback title"

    @pytest.mark.asyncio
    async def test_notification_android_fields_are_mapped(self, client):
        """Android-style notification payload keys map to model fields."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": [
                        {
                            "notificationId": "PostSharedWithMe:3000001:Badge",
                            "postTitle": "Afslutning for Lærer Et",
                            "notificationArea": "Posts",
                            "notificationEventType": "PostSharedWithMe",
                            "notificationType": "Badge",
                            "institutionCode": "G90001",
                            "triggered": "2026-02-27T08:57:31+00:00",
                            "expires": "2026-05-28T08:57:31+00:00",
                            "postId": 3000001,
                        }
                    ]
                },
            )
        )

        items = await client.get_notifications_for_active_profile(limit=1)
        assert len(items) == 1
        assert items[0].id == "PostSharedWithMe:3000001:Badge"
        assert items[0].title == "Afslutning for Lærer Et"
        assert items[0].module == "Posts"
        assert items[0].event_type == "PostSharedWithMe"
        assert items[0].notification_type == "Badge"
        assert items[0].institution_code == "G90001"
        assert items[0].created_at == "2026-02-27T08:57:31+00:00"
        assert items[0].expires_at == "2026-05-28T08:57:31+00:00"
        assert items[0].post_id == 3000001

    @pytest.mark.asyncio
    async def test_limit_is_applied_client_side(self, client):
        """Client-side limit protects output if API ignores limit."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": [
                        {"id": 1, "title": "A"},
                        {"id": 2, "title": "B"},
                    ]
                },
            )
        )

        items = await client.get_notifications_for_active_profile(limit=1)
        assert len(items) == 1
        assert items[0].title == "A"


class TestSearchMessages:
    """Tests for AulaApiClient.search_messages method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        c = AulaApiClient(http_client=http_client, access_token="test_token")
        c._access_token = None
        c._csrf_token = "csrf"
        return c

    @pytest.mark.asyncio
    async def test_single_page(self, client):
        """Single page of results is returned."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "results": [
                            search_hit({"id": "m1", "text": {"html": "<p>Hello</p>"}}),
                            search_hit({"id": "m2", "text": "Plain text"}),
                        ],
                        "totalSize": 2,
                    }
                },
            )
        )
        messages = await client.search_messages([1], ["INST1"])
        assert len(messages) == 2
        assert messages[0].content_html == "<p>Hello</p>"
        assert messages[1].content_html == "Plain text"

    @pytest.mark.asyncio
    async def test_multi_page_pagination(self, client):
        """Pagination fetches multiple pages until offset >= totalSize."""
        page1 = HttpResponse(
            status_code=200,
            data={
                "data": {
                    "results": [search_hit({"id": "m1", "text": "page1"})],
                    "totalSize": 2,
                }
            },
        )
        page2 = HttpResponse(
            status_code=200,
            data={
                "data": {
                    "results": [search_hit({"id": "m2", "text": "page2"})],
                    "totalSize": 2,
                }
            },
        )
        client._request_with_version_retry = AsyncMock(side_effect=[page1, page2])
        messages = await client.search_messages([1], ["INST1"], limit=1)
        assert len(messages) == 2
        assert client._request_with_version_retry.call_count == 2

    @pytest.mark.asyncio
    async def test_text_as_dict_vs_string(self, client):
        """Text field handled as dict with html key or as plain string."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "results": [
                            search_hit({"id": "m1", "text": {"html": "<b>bold</b>"}}),
                            search_hit({"id": "m2", "text": "plain"}),
                            search_hit({"id": "m3", "text": 12345}),
                        ],
                        "totalSize": 3,
                    }
                },
            )
        )
        messages = await client.search_messages([1], ["INST1"])
        assert messages[0].content_html == "<b>bold</b>"
        assert messages[1].content_html == "plain"
        assert messages[2].content_html == ""

    @pytest.mark.asyncio
    async def test_attachments_are_parsed(self, client):
        """A search filtered on attachments returns them on the message."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "results": [
                            search_hit(
                                {
                                    "id": "m1",
                                    "text": {"html": "<p>See the plan</p>"},
                                    "attachments": [
                                        {
                                            "id": 5002,
                                            "name": "weekplan.pdf",
                                            "file": {
                                                "name": "weekplan.pdf",
                                                "url": "https://files.example.test/weekplan.pdf",
                                            },
                                        }
                                    ],
                                }
                            )
                        ],
                        "totalSize": 1,
                    }
                },
            )
        )
        messages = await client.search_messages([1], ["INST1"], has_attachments=True)
        assert messages[0].has_attachments is True
        assert messages[0].attachments[0].url == "https://files.example.test/weekplan.pdf"

    @pytest.mark.asyncio
    async def test_empty_results_stops(self, client):
        """Empty results stops pagination immediately."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"results": [], "totalSize": 0}},
            )
        )
        messages = await client.search_messages([1], ["INST1"])
        assert messages == []
        assert client._request_with_version_retry.call_count == 1


class TestGetAllMessageThreads:
    """Tests for AulaApiClient.get_all_message_threads cutoff logic."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        c = AulaApiClient(http_client=http_client, access_token="test_token")
        return c

    @pytest.mark.asyncio
    async def test_stops_at_first_thread_older_than_cutoff(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "threads": [
                            thread_item("t1", "2026-03-01T10:00:00+01:00"),
                            thread_item("t2", "2026-01-01T10:00:00+01:00"),
                            thread_item("t3", "2026-03-01T10:00:00+01:00"),
                        ]
                    }
                },
            )
        )
        result = await client.get_all_message_threads_result(date(2026, 2, 1))
        assert result.termination_reason == "cutoff"
        assert [thread["id"] for thread in result.items] == ["t1"]
        assert client._request_with_version_retry.call_count == 1

    @pytest.mark.asyncio
    async def test_skips_threads_that_are_not_objects(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "threads": [
                            None,
                            "t0",
                            thread_item("t1", "2026-03-01T10:00:00+01:00"),
                            thread_item("t2", "2026-01-01T10:00:00+01:00"),
                        ]
                    }
                },
            )
        )
        result = await client.get_all_message_threads_result(date(2026, 2, 1))
        assert result.termination_reason == "cutoff"
        assert [thread["id"] for thread in result.items] == ["t1"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "undated",
        [
            {"id": "t1", "subject": "Emne Et"},
            {"id": "t1", "subject": "Emne Et", "latestMessage": {"id": "1000003"}},
            thread_item("t1", None),
            thread_item("t1", ""),
            thread_item("t1", "i går"),
        ],
        ids=["no-latest-message", "no-send-date-time", "null", "empty", "unparseable"],
    )
    async def test_undated_thread_does_not_stop_the_read(self, client, undated):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {"threads": [undated, thread_item("t2", "2026-01-01T10:00:00+01:00")]}
                },
            )
        )
        result = await client.get_all_message_threads_result(date(2026, 2, 1))
        assert result.termination_reason == "cutoff"
        assert [thread["id"] for thread in result.items] == ["t1"]


class TestGetAllMessagesForThread:
    """Tests for AulaApiClient.get_all_messages_for_thread pagination."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_collects_across_pages(self, client):
        """Messages are collected across multiple pages."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                HttpResponse(
                    status_code=200,
                    data={"data": {"messages": [{"id": "m1"}, {"id": "m2"}]}},
                ),
                HttpResponse(
                    status_code=200,
                    data={"data": {"messages": [{"id": "m3"}]}},
                ),
                HttpResponse(
                    status_code=200,
                    data={"data": {"messages": []}},
                ),
            ]
        )
        result = await client.get_all_messages_for_thread("t1")
        assert len(result) == 3
        assert [m["id"] for m in result] == ["m1", "m2", "m3"]

    @pytest.mark.asyncio
    async def test_stops_on_empty_page(self, client):
        """Stops immediately when first page is empty."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"messages": []}},
            )
        )
        result = await client.get_all_messages_for_thread("t1")
        assert result == []
        assert client._request_with_version_retry.call_count == 1


class TestGetGalleryAlbums:
    """Tests for AulaApiClient.get_gallery_albums response handling."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_data_is_list(self, client):
        """When data is a list, returned directly."""
        albums = [{"id": 1, "title": "Album 1"}]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": albums})
        )
        result = await client.get_gallery_albums([100])
        assert result == albums

    @pytest.mark.asyncio
    async def test_data_is_dict_with_albums_key(self, client):
        """When data is a dict, extracts albums key."""
        albums = [{"id": 2, "title": "Album 2"}]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": {"albums": albums}})
        )
        result = await client.get_gallery_albums([100])
        assert result == albums


class TestGetAlbumPictures:
    """Tests for AulaApiClient.get_album_pictures response handling."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_data_is_list(self, client):
        """When data is a list, returned directly."""
        pics = [{"id": 1, "file": {"url": "http://example.com/pic.jpg"}}]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": pics})
        )
        result = await client.get_album_pictures([100], album_id=1)
        assert result == pics

    @pytest.mark.asyncio
    async def test_data_is_dict_with_results_key(self, client):
        """When data is a dict, extracts results key."""
        pics = [{"id": 2, "file": {"url": "http://example.com/pic2.jpg"}}]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": {"results": pics}})
        )
        result = await client.get_album_pictures([100], album_id=1)
        assert result == pics


class TestGetPresenceRegistrations:
    """Tests for AulaApiClient.get_presence_registrations method."""

    @pytest.fixture
    def http(self):
        return FakeHttpClient()

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @pytest.mark.asyncio
    async def test_happy_path(self, client, http):
        http.aula(
            REGISTRATIONS,
            ok([{"id": 1, "institutionProfileId": 201, "status": 3, "date": "2026-03-08"}]),
        )
        result = await client.get_presence_registrations([201], date(2026, 3, 8), date(2026, 3, 8))
        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].institution_profile_id == 201
        assert http.calls(REGISTRATIONS)[0].query == {
            "method": REGISTRATIONS,
            "institutionProfileIds[]": [201],
            "fromDate": "2026-03-08",
            "toDate": "2026-03-08",
        }

    @pytest.mark.asyncio
    async def test_empty_data(self, client, http):
        http.aula(REGISTRATIONS, ok([]))
        result = await client.get_presence_registrations([201], date(2026, 3, 8), date(2026, 3, 8))
        assert result == []

    @pytest.mark.asyncio
    async def test_non_list_data(self, client, http):
        http.aula(REGISTRATIONS, ok(None))
        result = await client.get_presence_registrations([201], date(2026, 3, 8), date(2026, 3, 8))
        assert result == []

    @pytest.mark.asyncio
    async def test_batch_400_retries_each_profile_and_keeps_what_works(self, client, http):
        """One profile without presence must not blank out the others."""
        http.aula(
            REGISTRATIONS,
            http_status(400),
            ok([{"id": 1, "institutionProfileId": 201, "status": 3}]),
            http_status(400),
        )

        result = await client.get_presence_registrations(
            [201, 202], date(2026, 3, 8), date(2026, 3, 8)
        )

        assert [r.institution_profile_id for r in result] == [201]
        assert [c.query["institutionProfileIds[]"] for c in http.calls(REGISTRATIONS)] == [
            [201, 202],
            [201],
            [202],
        ]

    @pytest.mark.asyncio
    async def test_batch_400_raises_when_no_profile_can_be_read(self, client, http):
        http.aula(REGISTRATIONS, http_status(400))

        with pytest.raises(HttpRequestError):
            await client.get_presence_registrations([201, 202], date(2026, 3, 8), date(2026, 3, 8))

    @pytest.mark.asyncio
    async def test_single_profile_failure_is_not_retried(self, client, http):
        http.aula(REGISTRATIONS, http_status(400))

        with pytest.raises(HttpRequestError):
            await client.get_presence_registrations([201], date(2026, 3, 8), date(2026, 3, 8))

        assert len(http.calls(REGISTRATIONS)) == 1


class TestGetPresenceRegistrationDetail:
    """Tests for AulaApiClient.get_presence_registration_detail method."""

    @pytest.fixture
    def http(self):
        return FakeHttpClient()

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @pytest.mark.asyncio
    async def test_happy_path(self, client, http):
        http.aula(REGISTRATION_DETAIL, ok({"id": 555, "childName": "Barn Et", "status": 1}))
        result = await client.get_presence_registration_detail(555)
        assert result is not None
        assert result.id == 555
        assert result.child_name == "Barn Et"
        assert http.calls(REGISTRATION_DETAIL)[0].query["id"] == 555

    @pytest.mark.asyncio
    async def test_null_data(self, client, http):
        http.aula(REGISTRATION_DETAIL, ok(None))
        result = await client.get_presence_registration_detail(555)
        assert result is None


class TestGetPresenceStates:
    """Tests for AulaApiClient.get_presence_states method."""

    @pytest.fixture
    def http(self):
        http = FakeHttpClient()
        http.aula(STATES, ok([{"institutionProfileId": 201, "status": 3}]))
        return http

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @pytest.mark.asyncio
    async def test_happy_path(self, client, http):
        result = await client.get_presence_states([201])
        assert len(result) == 1
        assert result[0].institution_profile_id == 201
        assert http.calls(STATES)[0].query["institutionProfileIds[]"] == [201]

    @pytest.mark.asyncio
    async def test_no_filter(self, client, http):
        result = await client.get_presence_states()
        assert len(result) == 1
        assert "institutionProfileIds[]" not in http.calls(STATES)[0].query


class TestGetPresenceConfiguration:
    """Tests for AulaApiClient.get_presence_configuration method."""

    @pytest.fixture
    def http(self):
        return FakeHttpClient()

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @pytest.mark.asyncio
    async def test_happy_path(self, client, http):
        data = [
            {
                "uniStudentId": 201,
                "presenceConfiguration": {
                    "institution": {"institutionCode": "G90001", "name": "Skole Et"},
                    "pickup": True,
                    "goHomeWith": True,
                    "selfDecider": False,
                },
            }
        ]
        http.aula(CONFIGURATION, ok(data))
        result = await client.get_presence_configuration([201])
        assert len(result) == 1
        assert result[0].child_id == 201
        assert result[0].pickup is True
        assert http.calls(CONFIGURATION)[0].query["childIds[]"] == [201]

    @pytest.mark.asyncio
    async def test_empty_data(self, client, http):
        http.aula(CONFIGURATION, ok([]))
        result = await client.get_presence_configuration([201])
        assert result == []


class TestGetSecureDocuments:
    @pytest.fixture
    def client(self):
        return AulaApiClient(http_client=AsyncMock(), access_token="test_token")

    @staticmethod
    def _page(ids, more):
        documents = [{"id": i, "title": f"Dokument {i}"} for i in ids]
        return HttpResponse(
            status_code=200,
            data={"data": {"documents": documents, "moreDocumentsExists": more}},
        )

    @pytest.mark.asyncio
    async def test_posts_the_users_own_profiles_as_filter(self, client):
        client._request_with_version_retry = AsyncMock(return_value=self._page([1], False))

        await client.get_secure_documents([100])

        call = client._request_with_version_retry.call_args
        assert call.args[0] == "post"
        assert call.args[1].endswith("?method=documents.getSecureDocuments")
        assert call.kwargs["json"]["filterInstitutionProfileIds"] == [100]
        assert call.kwargs["json"]["index"] == 0

    @pytest.mark.asyncio
    async def test_reads_every_page_by_item_offset(self, client):
        client._request_with_version_retry = AsyncMock(
            side_effect=[self._page([1, 2], True), self._page([3], False)]
        )

        documents = await client.get_secure_documents([100], page_size=2)

        assert [d.id for d in documents] == [1, 2, 3]
        calls = client._request_with_version_retry.call_args_list
        assert [c.kwargs["json"]["index"] for c in calls] == [0, 2]


class TestGetCommonFiles:
    @pytest.fixture
    def client(self):
        return AulaApiClient(http_client=AsyncMock(), access_token="test_token")

    @staticmethod
    def _page(ids, total):
        files = [{"id": i, "title": f"Fil {i}"} for i in ids]
        return HttpResponse(
            status_code=200, data={"data": {"commonFiles": files, "totalAmount": total}}
        )

    @pytest.mark.asyncio
    async def test_asks_for_the_childrens_institutions(self, client):
        client._request_with_version_retry = AsyncMock(return_value=self._page([1], 1))

        await client.get_common_files(["280001"])

        params = client._request_with_version_retry.call_args.kwargs["params"]
        assert params["method"] == "commonFiles.getCommonFiles"
        assert params["institutionCodes[]"] == ["280001"]
        assert params["index"] == 0

    @pytest.mark.asyncio
    async def test_reads_every_page_by_item_offset(self, client):
        client._request_with_version_retry = AsyncMock(
            side_effect=[self._page([1, 2], 3), self._page([3], 3)]
        )

        files = await client.get_common_files(["280001"], page_size=2)

        assert [f.id for f in files] == [1, 2, 3]
        calls = client._request_with_version_retry.call_args_list
        assert [c.kwargs["params"]["index"] for c in calls] == [0, 2]

    @pytest.mark.asyncio
    async def test_stops_when_a_page_comes_back_empty(self, client):
        client._request_with_version_retry = AsyncMock(return_value=self._page([], 5))

        assert await client.get_common_files(["280001"]) == []
        assert client._request_with_version_retry.call_count == 1

    @pytest.mark.asyncio
    async def test_no_institutions_makes_no_request(self, client):
        client._request_with_version_retry = AsyncMock()

        assert await client.get_common_files([]) == []
        client._request_with_version_retry.assert_not_called()


class TestSearchGroups:
    @pytest.mark.asyncio
    async def test_uses_the_portal_search_method(self):
        client = AulaApiClient(http_client=AsyncMock(), access_token="test_token")
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"results": [{"id": "12345", "name": "3.A"}], "totalSize": 1}},
            )
        )

        groups = await client.search_groups("3.A")

        params = client._request_with_version_retry.call_args.kwargs["params"]
        assert params["method"] == "search.findGroups"
        assert params["text"] == "3.A"
        assert [(g.id, g.name) for g in groups] == [(12345, "3.A")]


class TestGetVacationRegistrations:
    """Tests for AulaApiClient.get_vacation_registrations method."""

    @pytest.fixture
    def http(self):
        return FakeHttpClient()

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @pytest.mark.asyncio
    async def test_happy_path_flattens_groups(self, client, http):
        data = [
            {
                "child": {"id": 201, "name": "Barn Et"},
                "vacationRegistrations": [
                    {
                        "vacationRegistrationId": 1,
                        "title": "Sommerferie",
                        "startDate": "2026-07-01",
                        "endDate": "2026-07-14",
                    },
                    {"vacationRegistrationId": 2, "title": "Efterårsferie"},
                ],
            },
            {
                "child": {"id": 202, "name": "Barn To"},
                "vacationRegistrations": [{"vacationRegistrationId": 3, "title": "Juleferie"}],
            },
        ]
        http.aula(VACATIONS, ok(data))

        result = await client.get_vacation_registrations([201, 202])

        assert [r.id for r in result] == [1, 2, 3]
        assert [r.child_id for r in result] == [201, 201, 202]
        assert [r.child_name for r in result] == ["Barn Et", "Barn Et", "Barn To"]
        assert result[0].start_date == "2026-07-01"

    @pytest.mark.asyncio
    async def test_sends_child_ids_to_by_children_method(self, client, http):
        http.aula(VACATIONS, ok([]))

        await client.get_vacation_registrations([201, 202])

        assert http.calls(VACATIONS)[0].query == {
            "method": "presence.getVacationRegistrationsByChildren",
            "childIds[]": [201, 202],
        }

    @pytest.mark.asyncio
    async def test_empty_data(self, client, http):
        http.aula(VACATIONS, ok([]))

        assert await client.get_vacation_registrations([201]) == []

    @pytest.mark.asyncio
    async def test_skips_groups_without_registrations(self, client, http):
        data = [
            {"child": {"id": 201, "name": "Barn Et"}},
            {"child": {"id": 202, "name": "Barn To"}, "vacationRegistrations": None},
            "not-a-group",
            {
                "child": {"id": 203, "name": "Barn Tre"},
                "vacationRegistrations": [{"vacationRegistrationId": 5}, "not-a-row"],
            },
        ]
        http.aula(VACATIONS, ok(data))

        result = await client.get_vacation_registrations([201, 202, 203])

        assert [r.id for r in result] == [5]
        assert result[0].child_name == "Barn Tre"

    @pytest.mark.asyncio
    async def test_group_without_child_still_parses(self, client, http):
        http.aula(
            VACATIONS,
            ok([{"vacationRegistrations": [{"vacationRegistrationId": 9, "title": "Ferie"}]}]),
        )

        result = await client.get_vacation_registrations([201])

        assert result[0].id == 9
        assert result[0].child_id == 0

    @pytest.mark.asyncio
    async def test_non_list_data(self, client, http):
        http.aula(VACATIONS, ok(None))

        assert await client.get_vacation_registrations([201]) == []


class TestGetActivityOverview:
    """Tests for AulaApiClient.get_activity_overview method."""

    @pytest.fixture
    def http(self):
        return FakeHttpClient()

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @pytest.mark.asyncio
    async def test_happy_path(self, client, http):
        data = {
            "days": [
                {
                    "date": "2026-03-02",
                    "activities": [
                        {"title": "Matematik", "startTime": "08:00", "endTime": "09:00"}
                    ],
                }
            ]
        }
        http.aula(ACTIVITY, ok(data))
        result = await client.get_activity_overview([201], week=10, year=2026)
        assert result is not None
        assert len(result.days) == 1
        assert result.days[0].activities[0].title == "Matematik"
        assert http.calls(ACTIVITY)[0].query == {
            "method": ACTIVITY,
            "institutionProfileIds[]": [201],
            "week": 10,
            "year": 2026,
        }

    @pytest.mark.asyncio
    async def test_null_data(self, client, http):
        http.aula(ACTIVITY, ok(None))
        result = await client.get_activity_overview([201], week=10, year=2026)
        assert result is None


class TestGetGroups:
    """Tests for AulaApiClient.get_groups method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        """The live API wraps groups in a list of per-profile contexts."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": [
                        {
                            "profileId": 2000002,
                            "displayName": "Parent Name",
                            "groups": [
                                {
                                    "id": 1,
                                    "name": "Class 3A",
                                    "type": "primary",
                                    "institutionCode": "123456",
                                    "description": "Main group",
                                }
                            ],
                        }
                    ]
                },
            )
        )
        result = await client.get_groups(institution_codes=["123456"])
        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].name == "Class 3A"
        assert result[0].group_type == "primary"

    @pytest.mark.asyncio
    async def test_institution_codes_filter(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        await client.get_groups(institution_codes=["123456"])
        params = client._request_with_version_retry.call_args.kwargs["params"]
        assert params["institutionCodes[]"] == ["123456"]
        assert "childInstitutionProfileIds[]" not in params

    @pytest.mark.asyncio
    async def test_child_filter_wins_and_is_exclusive(self, client):
        """Sending both filters together answers HTTP 400, so only one goes out."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        await client.get_groups(
            institution_codes=["123456"], child_institution_profile_ids=[100, 200]
        )
        params = client._request_with_version_retry.call_args.kwargs["params"]
        assert params["childInstitutionProfileIds[]"] == [100, 200]
        assert "institutionCodes[]" not in params

    @pytest.mark.asyncio
    async def test_requires_a_filter(self, client):
        client._request_with_version_retry = AsyncMock()
        with pytest.raises(ValueError, match="requires either"):
            await client.get_groups()
        client._request_with_version_retry.assert_not_called()

    @pytest.mark.asyncio
    async def test_flattens_and_dedupes_contexts(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": [
                        {"profileId": 1, "groups": [{"id": 10, "name": "Shared"}]},
                        {
                            "profileId": 2,
                            "groups": [
                                {"id": 10, "name": "Shared"},
                                {"id": 11, "name": "Other"},
                            ],
                        },
                    ]
                },
            )
        )
        result = await client.get_groups(institution_codes=["123"])
        assert [g.id for g in result] == [10, 11]

    @pytest.mark.asyncio
    async def test_dict_shaped_data(self, client):
        """A dict-shaped ``data`` with a top-level groups list is still accepted."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"groups": [{"id": 1, "name": "Class 3A"}]}},
            )
        )
        result = await client.get_groups(institution_codes=["123"])
        assert [g.name for g in result] == ["Class 3A"]

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_groups(institution_codes=["123"])
        assert result == []

    @pytest.mark.asyncio
    async def test_null_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": None})
        )
        result = await client.get_groups(institution_codes=["123"])
        assert result == []

    @pytest.mark.asyncio
    async def test_malformed_item_skipped(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": [
                        {
                            "profileId": 1,
                            "groups": [
                                {"id": 1, "name": "Good"},
                                "not-a-dict",
                                {"no_id": True},
                            ],
                        },
                        "not-a-context",
                    ]
                },
            )
        )
        result = await client.get_groups(institution_codes=["123"])
        assert len(result) == 1
        assert result[0].name == "Good"


class TestGetGroup:
    """Tests for AulaApiClient.get_group method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"id": 5, "name": "Group X", "type": "SFO"}},
            )
        )
        result = await client.get_group(5)
        assert result is not None
        assert result.id == 5
        assert result.name == "Group X"

    @pytest.mark.asyncio
    async def test_null_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": None})
        )
        result = await client.get_group(5)
        assert result is None


class TestGetGroupMembers:
    """Tests for AulaApiClient.get_group_members method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": [
                        {
                            "institutionProfileId": 42,
                            "name": "Alice",
                            "portalRole": "guardian",
                        }
                    ]
                },
            )
        )
        result = await client.get_group_members(1)
        assert len(result) == 1
        assert result[0].institution_profile_id == 42
        assert result[0].name == "Alice"

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_group_members(1)
        assert result == []


class TestGetCalendarEvent:
    """Tests for AulaApiClient.get_calendar_event method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"id": 1, "title": "Parent meeting"}},
            )
        )
        result = await client.get_calendar_event(1)
        assert result is not None
        assert result["id"] == 1

    @pytest.mark.asyncio
    async def test_null_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": None})
        )
        result = await client.get_calendar_event(1)
        assert result is None

    @pytest.mark.asyncio
    async def test_with_occurrence_datetime(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"id": 1, "title": "Recurring"}},
            )
        )
        result = await client.get_calendar_event(1, occurrence_datetime="2026-03-16")
        assert result is not None
        client._request_with_version_retry.assert_called_once()
        call_kwargs = client._request_with_version_retry.call_args
        assert call_kwargs[1]["params"]["occurrenceDateTime"] == "2026-03-16"


class TestGetImportantDates:
    """Tests for AulaApiClient.get_important_dates method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"id": 1, "title": "School holiday"}]},
            )
        )
        result = await client.get_important_dates()
        assert len(result) == 1
        assert result[0]["title"] == "School holiday"

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_important_dates()
        assert result == []


class TestGetBirthdayEvents:
    """Tests for AulaApiClient.get_birthday_events method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"name": "Alice", "birthday": "2020-03-16"}]},
            )
        )
        result = await client.get_birthday_events(["INST1"], "2026-03-01", "2026-03-31")
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_birthday_events(["INST1"], "2026-03-01", "2026-03-31")
        assert result == []


class TestGetBirthdayEventsForGroup:
    """Tests for AulaApiClient.get_birthday_events_for_group method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"name": "Bob", "birthday": "2019-05-10"}]},
            )
        )
        result = await client.get_birthday_events_for_group(42, "2026-03-01", "2026-03-31")
        assert len(result) == 1
        assert result[0]["name"] == "Bob"


class TestGetEventTypes:
    """Tests for AulaApiClient.get_event_types method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"id": 1, "name": "Meeting"}]},
            )
        )
        result = await client.get_event_types()
        assert len(result) == 1
        assert result[0]["name"] == "Meeting"


class TestGetDailyAggregatedEvents:
    """Tests for AulaApiClient.get_daily_aggregated_events method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"date": "2026-03-16", "count": 3}]},
            )
        )
        result = await client.get_daily_aggregated_events([1, 2], "2026-03-01", "2026-03-31")
        assert len(result) == 1
        assert result[0]["count"] == 3


class TestGetEventsForInstitutions:
    """Tests for AulaApiClient.get_events_for_institutions method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"id": 1, "title": "School event"}]},
            )
        )
        result = await client.get_events_for_institutions(["INST1"], "2026-03-01", "2026-03-31")
        assert len(result) == 1
        assert result[0]["title"] == "School event"


class TestGetDailyEventCountForGroup:
    """Tests for AulaApiClient.get_daily_event_count_for_group method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"date": "2026-03-16", "count": 5}]},
            )
        )
        result = await client.get_daily_event_count_for_group(42, "2026-03-01", "2026-03-31")
        assert len(result) == 1
        assert result[0]["count"] == 5


class TestGetEventsByGroup:
    """Tests for AulaApiClient.get_events_by_group method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"id": 1, "title": "Group event"}]},
            )
        )
        result = await client.get_events_by_group(42, "2026-03-01", "2026-03-31")
        assert len(result) == 1
        assert result[0]["title"] == "Group event"


class TestGetPost:
    """Tests for AulaApiClient.get_post method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "id": 1,
                        "title": "Test Post",
                        "content": {"html": "<p>content</p>"},
                        "ownerProfile": {
                            "id": 10,
                            "profileId": 20,
                            "name": "Author",
                        },
                    }
                },
            )
        )
        result = await client.get_post(1)
        assert result is not None
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_null_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": None})
        )
        result = await client.get_post(1)
        assert result is None


class TestGetComments:
    """Tests for AulaApiClient.get_comments method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": [
                        {
                            "id": 1,
                            "text": "Nice!",
                            "owner": {"name": "Bob", "institutionProfileId": 10},
                            "createdAt": "2026-03-16",
                        }
                    ]
                },
            )
        )
        result = await client.get_comments("post", 1)
        assert len(result) == 1
        assert result[0].id == 1

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_comments("post", 1)
        assert result == []

    @pytest.mark.asyncio
    async def test_malformed_item_skipped(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": [
                        {"id": 1, "text": "Good", "owner": {"name": "A"}},
                        "bad-item",
                    ]
                },
            )
        )
        result = await client.get_comments("post", 1)
        assert len(result) == 1


# ── Section 4: Gallery Reads ──────────────────────────────────────
class TestGetMediaById:
    """Tests for AulaApiClient.get_media_by_id method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"id": 10, "title": "Photo"}},
            )
        )
        result = await client.get_media_by_id(10)
        assert result is not None
        assert result["id"] == 10

    @pytest.mark.asyncio
    async def test_null_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": None})
        )
        result = await client.get_media_by_id(10)
        assert result is None


class TestGetMediaByProfile:
    """Tests for AulaApiClient.get_media_by_profile method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        media = [{"id": 1, "title": "Pic1"}, {"id": 2, "title": "Pic2"}]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": media})
        )
        result = await client.get_media_by_profile(100)
        assert len(result) == 2
        assert result[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_media_by_profile(100)
        assert result == []


# ── Section 5: Messaging Reads ────────────────────────────────────
class TestGetMessageFolders:
    """Tests for AulaApiClient.get_message_folders method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"id": 1, "name": "Inbox"}, {"id": 2, "name": "Sent"}]},
            )
        )
        result = await client.get_message_folders()
        assert len(result) == 2
        assert result[0].id == 1
        assert result[0].name == "Inbox"

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_message_folders()
        assert result == []


class TestGetCommonInboxes:
    """Tests for AulaApiClient.get_common_inboxes method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        inboxes = [{"id": 1, "name": "School Inbox"}]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": inboxes})
        )
        result = await client.get_common_inboxes()
        assert len(result) == 1
        assert result[0]["name"] == "School Inbox"

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_common_inboxes()
        assert result == []


class TestGetThreadsInBundle:
    """Tests for AulaApiClient.get_threads_in_bundle method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": [{"id": "t1", "subject": "Hello"}]},
            )
        )
        result = await client.get_threads_in_bundle(42)
        assert len(result) == 1
        assert result[0].thread_id == "t1"
        assert result[0].subject == "Hello"

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_threads_in_bundle(42)
        assert result == []


class TestGetMessageInfo:
    """Tests for AulaApiClient.get_message_info method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"threadId": "t1", "messageId": "m1", "text": "Hi"}},
            )
        )
        result = await client.get_message_info("t1", "m1")
        assert result is not None
        assert result["messageId"] == "m1"


# ── Section 6: Search ─────────────────────────────────────────────
class TestFindRecipients:
    """Tests for AulaApiClient.find_recipients method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"results": [{"name": "Alice", "id": 1}]}},
            )
        )
        result = await client.find_recipients("Alice")
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_empty_results(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"results": []}},
            )
        )
        result = await client.find_recipients("Nobody")
        assert result == []


class TestFindProfilesAndGroups:
    """Tests for AulaApiClient.find_profiles_and_groups method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"profiles": [{"name": "Alice"}], "groups": []}},
            )
        )
        result = await client.find_profiles_and_groups("Alice")
        assert isinstance(result, dict)
        assert len(result["profiles"]) == 1


class TestSearch:
    """Tests for AulaApiClient.search method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"results": [{"title": "Math homework"}], "totalCount": 1}},
            )
        )
        result = await client.search("Math")
        assert isinstance(result, dict)
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_empty_results(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"results": [], "totalCount": 0}},
            )
        )
        result = await client.search("nonexistent")
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_with_doc_type_filter(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"results": [{"title": "Post 1"}], "totalCount": 1}},
            )
        )
        result = await client.search("test", doc_type="post")
        assert len(result["results"]) == 1
        call_kwargs = client._request_with_version_retry.call_args
        assert call_kwargs[1]["params"]["DocType"] == "post"


# ── Section 7: Contacts ───────────────────────────────────────────
class TestGetContactList:
    """Tests for AulaApiClient.get_contact_list method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        contacts = [{"name": "Alice", "role": "guardian"}]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": contacts})
        )
        result = await client.get_contact_list(42)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_contact_list(42)
        assert result == []

    @pytest.mark.asyncio
    async def test_sends_all_required_params(self, client):
        """The API 400s unless method casing and every param are exactly right."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        await client.get_contact_list(42)
        params = client._request_with_version_retry.call_args.kwargs["params"]
        assert params == {
            "method": "profiles.getContactlist",
            "groupId": 42,
            "filter": "guardian",
            "field": "name",
            "page": 1,
            "order": "asc",
        }

    @pytest.mark.asyncio
    async def test_profile_type_and_page_forwarded(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        await client.get_contact_list(42, page=3, order="desc", profile_type="child")
        params = client._request_with_version_retry.call_args.kwargs["params"]
        assert params["filter"] == "child"
        assert params["page"] == 3
        assert params["order"] == "desc"


class TestGetContactParents:
    """Tests for AulaApiClient.get_contact_parents method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        parents = [{"name": "Bob", "role": "parent"}]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": parents})
        )
        result = await client.get_contact_parents()
        assert len(result) == 1
        assert result[0]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_empty_data(self, client):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_contact_parents()
        assert result == []

    @pytest.mark.asyncio
    async def test_sends_required_params(self, client):
        """page and order are required; omitting them answers HTTP 400."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        await client.get_contact_parents()
        params = client._request_with_version_retry.call_args.kwargs["params"]
        assert params == {
            "method": "profiles.getContactParents",
            "page": 1,
            "order": "asc",
        }


class TestUpdatePresenceTemplate:
    """Tests for AulaApiClient.update_presence_template method."""

    @pytest.fixture
    def http(self):
        http = FakeHttpClient()
        http.aula(UPDATE_TEMPLATE, ok())
        return http

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @staticmethod
    def _payload(http):
        """Return the JSON body of the recorded request."""
        [call] = http.calls(UPDATE_TEMPLATE)
        assert call.method == "post"
        return call.json

    @pytest.mark.asyncio
    async def test_accepts_activity_type_enum(self, client, http):
        """An ActivityType member is serialised as its int value."""
        from aula.models.presence import ActivityType

        await client.update_presence_template(
            institution_profile_id=10,
            by_date=date(2026, 2, 25),
            entry_time="08:00",
            exit_time="16:00",
            activity_type=ActivityType.GO_HOME_WITH,
            exit_with="Værge Et (Far)",
        )

        activity = self._payload(http)["presenceActivity"]
        assert activity["activityType"] == 3
        assert activity["goHomeWith"] == {
            "entryTime": "08:00",
            "exitTime": "16:00",
            "exitWith": "Værge Et (Far)",
        }

    @pytest.mark.asyncio
    async def test_accepts_raw_int_for_compatibility(self, client, http):
        """A raw int still selects the same activity shape as the enum."""
        await client.update_presence_template(
            institution_profile_id=10,
            by_date=date(2026, 2, 25),
            entry_time="08:00",
            exit_time="16:00",
            activity_type=1,
        )

        activity = self._payload(http)["presenceActivity"]
        assert activity["activityType"] == 1
        assert activity["selfDecider"] == {
            "entryTime": "08:00",
            "exitStartTime": "16:00",
            "exitEndTime": "16:00",
        }

    @pytest.mark.asyncio
    async def test_self_decider_leaves_within_a_window(self, client, http):
        """A self-decider may leave between exit_time and self_decider_end_time."""
        from aula.models.presence import ActivityType

        await client.update_presence_template(
            institution_profile_id=10,
            by_date=date(2026, 2, 25),
            entry_time="08:00",
            exit_time="14:00",
            activity_type=ActivityType.SELF_DECIDER,
            self_decider_end_time="16:00",
        )

        activity = self._payload(http)["presenceActivity"]
        assert activity["selfDecider"] == {
            "entryTime": "08:00",
            "exitStartTime": "14:00",
            "exitEndTime": "16:00",
        }

    @pytest.mark.asyncio
    async def test_self_decider_end_time_needs_self_decider(self, client, http):
        """Any other activity type would drop the end time, so it is refused."""
        with pytest.raises(ValueError, match="self_decider_end_time"):
            await client.update_presence_template(
                institution_profile_id=10,
                by_date=date(2026, 2, 25),
                entry_time="08:00",
                exit_time="14:00",
                exit_with="Mor",
                self_decider_end_time="16:00",
            )

        assert http.requests == []

    @pytest.mark.asyncio
    async def test_defaults_to_picked_up_by(self, client, http):
        """Omitting activity_type keeps the previous default of 0."""
        await client.update_presence_template(
            institution_profile_id=10,
            by_date=date(2026, 2, 25),
            entry_time="08:00",
            exit_time="16:00",
            exit_with="Mor",
        )

        activity = self._payload(http)["presenceActivity"]
        assert activity["activityType"] == 0
        assert activity["pickup"]["exitWith"] == "Mor"

    @pytest.mark.asyncio
    async def test_unknown_activity_type_uses_flat_shape(self, client, http):
        """An int Aula adds later is passed through rather than rejected."""
        await client.update_presence_template(
            institution_profile_id=10,
            by_date=date(2026, 2, 25),
            entry_time="08:00",
            exit_time="16:00",
            activity_type=99,
        )

        activity = self._payload(http)["presenceActivity"]
        assert activity == {
            "activityType": 99,
            "entryTime": "08:00",
            "exitTime": "16:00",
        }

    @pytest.mark.asyncio
    async def test_drop_off_time_uses_flat_shape(self, client, http):
        """DROP_OFF_TIME has no nested sub-object."""
        from aula.models.presence import ActivityType

        await client.update_presence_template(
            institution_profile_id=10,
            by_date=date(2026, 2, 25),
            entry_time="08:00",
            exit_time="16:00",
            activity_type=ActivityType.DROP_OFF_TIME,
        )

        activity = self._payload(http)["presenceActivity"]
        assert activity == {
            "activityType": 4,
            "entryTime": "08:00",
            "exitTime": "16:00",
        }


class TestUpdatePresenceStatus:
    """Tests for AulaApiClient.update_presence_status method."""

    @pytest.fixture
    def http(self):
        http = FakeHttpClient()
        http.aula(UPDATE_STATUS, ok(True))
        return http

    @pytest.fixture
    def client(self, http):
        return AulaApiClient(http)

    @staticmethod
    def _sent(http):
        """Return the one recorded request."""
        [call] = http.calls(UPDATE_STATUS)
        return call

    @pytest.mark.asyncio
    async def test_posts_sick_status_for_profile_ids(self, client, http):
        """The sick report is a POST of profile IDs plus the status number."""
        from aula.models.presence import PresenceState

        result = await client.update_presence_status([201, 202], PresenceState.SICK)

        sent = self._sent(http)
        assert sent.method == "post"
        assert sent.url.endswith("?method=presence.updateStatusByInstitutionProfileIds")
        assert sent.json == {
            "institutionProfileIds": [201, 202],
            "status": 1,
        }
        assert result is True

    @pytest.mark.asyncio
    async def test_undo_sends_not_present(self, client, http):
        """Taking the report back is the same call with a different status."""
        from aula.models.presence import PresenceState

        await client.update_presence_status([201], PresenceState.NOT_PRESENT)

        assert self._sent(http).json["status"] == 0

    @pytest.mark.asyncio
    async def test_accepts_raw_int_for_compatibility(self, client, http):
        """A status Aula adds later still reaches the backend."""
        await client.update_presence_status([201], 42)

        assert self._sent(http).json["status"] == 42

    @pytest.mark.asyncio
    async def test_returns_the_boolean_aula_answers_with(self, client, http):
        """A false body is reported as failure, not swallowed."""
        from aula.models.presence import PresenceState

        http.aula(UPDATE_STATUS, ok(False))

        assert await client.update_presence_status([201], PresenceState.SICK) is False

    @pytest.mark.asyncio
    async def test_missing_data_is_treated_as_success(self, client, http):
        """Aula answering without a body is not a failure signal."""
        from aula.models.presence import PresenceState

        http.aula(UPDATE_STATUS, http_status(200, {"status": {"code": 0}}))

        assert await client.update_presence_status([201], PresenceState.SICK) is True

    @pytest.mark.asyncio
    async def test_empty_profile_ids_raises_before_the_request(self, client, http):
        """An empty list would write nothing, so it is a caller error."""
        from aula.models.presence import PresenceState

        with pytest.raises(ValueError, match="at least one profile ID"):
            await client.update_presence_status([], PresenceState.SICK)

        assert http.requests == []


class TestValidateVacation:
    """The portal's own form rules, checked before an absence is sent."""

    TODAY = date(2026, 11, 2)

    def _validate(self, start, end, comment=""):
        validate_vacation(start, end, comment, today=self.TODAY)

    def test_same_day_absence_is_valid(self):
        """A single day is the commonest absence, so start may equal end."""
        self._validate(self.TODAY, self.TODAY)

    def test_start_in_the_past_is_rejected(self):
        """The portal does not let a guardian register an absence after the fact."""
        with pytest.raises(ValueError, match="past"):
            self._validate(date(2026, 11, 1), date(2026, 11, 3))

    def test_reversed_dates_are_rejected(self):
        """An end before the start is a typo, not an empty absence."""
        with pytest.raises(ValueError, match="before start date"):
            self._validate(date(2026, 11, 6), date(2026, 11, 5))

    def test_end_exactly_one_calendar_year_after_start_is_valid(self):
        """The portal's limit is inclusive of the same date next year."""
        self._validate(date(2026, 11, 2), date(2027, 11, 2))

    def test_end_past_one_calendar_year_is_rejected(self):
        """One day past the portal's limit is refused before any write."""
        with pytest.raises(ValueError, match="more than a year"):
            self._validate(date(2026, 11, 2), date(2027, 11, 3))

    def test_year_spanning_a_leap_day_allows_366_days(self):
        """The limit is a calendar year, not a fixed 365 days."""
        validate_vacation(date(2027, 3, 1), date(2028, 3, 1), "", today=date(2027, 3, 1))

    def test_leap_day_start_ends_on_28_february_next_year(self):
        """29 February has no anniversary, so the year ends on the 28th."""
        today = date(2028, 2, 29)
        validate_vacation(today, date(2029, 2, 28), "", today=today)
        with pytest.raises(ValueError, match="latest 2029-02-28"):
            validate_vacation(today, date(2029, 3, 1), "", today=today)

    def test_comment_of_250_characters_is_valid(self):
        """The portal caps the comment at exactly 250 characters."""
        self._validate(self.TODAY, self.TODAY, "x" * 250)

    def test_comment_of_251_characters_is_rejected(self):
        """A longer comment would be cut or refused, so it is stopped here."""
        with pytest.raises(ValueError, match="251 characters"):
            self._validate(self.TODAY, self.TODAY, "x" * 251)


class TestAddVacation:
    """Tests for AulaApiClient.add_vacation, the planned-absence write."""

    TODAY = date(2026, 11, 2)

    @pytest.fixture(autouse=True)
    def _fixed_today(self, monkeypatch):
        monkeypatch.setattr("aula.api_client.aula_today", lambda: self.TODAY)

    @staticmethod
    def _client(*answers):
        """A client whose transport answers calendar.addVacation with ``answers`` in turn."""
        http = FakeHttpClient()
        if answers:
            http.aula(ADD_VACATION, *answers)
        return AulaApiClient(http), http

    @pytest.mark.asyncio
    async def test_posts_the_portal_payload_to_add_vacation(self):
        """The body must match what the guardian portal sends, key for key."""
        client, http = self._client(ok())

        result = await client.add_vacation(
            [201, 202], date(2026, 11, 2), date(2026, 11, 6), "Familietur"
        )

        [sent] = http.calls(ADD_VACATION)
        assert sent.method == "post"
        assert sent.url == f"{API_URL}{API_VERSION}?method=calendar.addVacation"
        assert sent.json == {
            "childIds": [201, 202],
            "intervals": [{"startDate": "2026-11-02", "endDate": "2026-11-06"}],
            "comment": "Familietur",
        }
        assert result is True

    @pytest.mark.asyncio
    async def test_omitted_comment_is_sent_as_empty_string(self):
        """The portal sends an empty string, not null or a missing key."""
        client, http = self._client(http_status(200, {"status": {"code": 0}}))

        await client.add_vacation([201], self.TODAY, self.TODAY)

        assert http.calls(ADD_VACATION)[0].json["comment"] == ""

    @pytest.mark.asyncio
    async def test_empty_child_ids_raise_before_the_request(self):
        """An empty list would write nothing, so it is a caller error."""
        client, http = self._client()

        with pytest.raises(ValueError, match="at least one child ID"):
            await client.add_vacation([], self.TODAY, self.TODAY)

        assert http.requests == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("start", "end", "comment"),
        [
            (date(2026, 11, 1), date(2026, 11, 2), ""),
            (date(2026, 11, 6), date(2026, 11, 2), ""),
            (date(2026, 11, 2), date(2027, 11, 3), ""),
            (date(2026, 11, 2), date(2026, 11, 2), "x" * 251),
        ],
        ids=["past start", "reversed", "over a year", "long comment"],
    )
    async def test_invalid_absence_raises_before_the_request(self, start, end, comment):
        """A library caller gets the same checks as the CLI, before anything is written."""
        client, http = self._client()

        with pytest.raises(ValueError):
            await client.add_vacation([201], start, end, comment)

        assert http.requests == []

    @pytest.mark.asyncio
    async def test_aula_rejection_raises(self):
        """An error envelope on HTTP 200 must not read as a registered absence."""
        client, _ = self._client(rejected(10, 33))

        with pytest.raises(AulaRejectedError, match="calendar.addVacation"):
            await client.add_vacation([201], self.TODAY, self.TODAY)

    @pytest.mark.asyncio
    async def test_http_failure_raises(self):
        """A server error must not read as a registered absence."""
        client, _ = self._client(http_status(500, {"status": {"code": 0}}))

        with pytest.raises(AulaServerError):
            await client.add_vacation([201], self.TODAY, self.TODAY)


class TestMarkThreadRead:
    """Tests for AulaApiClient.mark_thread_read method.

    The responses are real ``HttpResponse`` objects, so the HTTP-status check and the
    check of Aula's own status envelope both run.
    """

    OWNER = {"mailBoxOwnerType": "institutionProfile", "id": 1}

    MISSING = object()

    @classmethod
    def _page(cls, messages, *, more=False, last_read=None, owner=OWNER, code=0, http=200):
        data = {
            "messages": messages,
            "moreMessagesExist": more,
            "lastReadMessageId": last_read,
        }
        if owner is not cls.MISSING:
            data["mailBoxOwner"] = owner
        return HttpResponse(status_code=http, data={"status": {"code": code}, "data": data})

    @staticmethod
    def _ok():
        return HttpResponse(status_code=200, data={"status": {"code": 0}, "data": None})

    @staticmethod
    def _client(*responses):
        client = AulaApiClient(http_client=AsyncMock(), access_token="test_token")
        client._request_with_version_retry = AsyncMock(side_effect=list(responses))
        return client

    @staticmethod
    def _msg(msg_id, message_type="Message"):
        return {"id": msg_id, "messageType": message_type}

    @staticmethod
    def _calls(client):
        return [
            (c.args[0], c.args[1], c.kwargs)
            for c in client._request_with_version_retry.await_args_list
        ]

    @pytest.mark.asyncio
    async def test_sets_the_marker_on_the_newest_message_and_checks_it(self):
        """Aula lists the newest message first, and that is where the marker goes."""
        client = self._client(
            self._page([self._msg("new"), self._msg("old")]),
            self._ok(),
            self._page([self._msg("new")], last_read="new"),
        )

        assert await client.mark_thread_read("42") is True

        get_call, post_call, check_call = self._calls(client)
        assert get_call[0] == "get"
        assert "method=messaging.getMessagesForThread&threadId=42&page=0" in get_call[1]
        assert post_call[0] == "post"
        assert post_call[1].endswith("?method=messaging.setLastReadMessage")
        assert post_call[2]["json"] == {
            "threadId": "42",
            "messageId": "new",
            "commonInboxId": None,
            "otpInboxId": None,
        }
        assert check_call[0] == "get"

    @pytest.mark.asyncio
    async def test_skips_entries_that_are_not_messages(self):
        """A thread event such as a recipient change is not a message to mark."""
        client = self._client(
            self._page(
                [self._msg("event", "RecipientsRemoved"), self._msg("msg", "MessageEdited")]
            ),
            self._ok(),
            self._page([], last_read="msg"),
        )

        assert await client.mark_thread_read("42") is True

        assert self._calls(client)[1][2]["json"]["messageId"] == "msg"

    @pytest.mark.asyncio
    async def test_keeps_paging_when_the_first_page_holds_only_events(self):
        """Events on page 0 do not mean the thread has no message."""
        client = self._client(
            self._page([self._msg("event", "RecipientsAdded")], more=True),
            self._page([self._msg("msg")]),
            self._ok(),
            self._page([], last_read="msg"),
        )

        assert await client.mark_thread_read("42") is True

        calls = self._calls(client)
        assert "page=0" in calls[0][1]
        assert "page=1" in calls[1][1]
        assert calls[2][2]["json"]["messageId"] == "msg"

    @pytest.mark.asyncio
    async def test_thread_without_messages_is_not_written(self):
        """With nothing to mark once every page is read, no write is sent."""
        client = self._client(self._page([self._msg("event", "RecipientsAdded")]))

        assert await client.mark_thread_read("42") is False

        assert len(self._calls(client)) == 1

    @pytest.mark.asyncio
    async def test_api_error_in_a_200_answer_is_not_success(self):
        """Aula reports its own errors inside an HTTP 200."""
        rejected = HttpResponse(status_code=200, data={"status": {"code": 5}, "data": None})
        client = self._client(self._page([self._msg("new")]), rejected)

        with pytest.raises(HttpRequestError, match="rejected messaging.setLastReadMessage"):
            await client.mark_thread_read("42")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [None, "", "<html>", [], {}, {"status": "ok"}, {"data": {}}])
    async def test_malformed_answer_is_not_success(self, body):
        """An empty or unexpected body is not read as a success."""
        client = self._client(
            self._page([self._msg("new")]), HttpResponse(status_code=200, data=body)
        )

        with pytest.raises(HttpRequestError):
            await client.mark_thread_read("42")

    @pytest.mark.asyncio
    async def test_api_error_while_reading_the_thread_writes_nothing(self):
        """A rejected read stops before any write."""
        client = self._client(self._page([self._msg("new")], code=1))

        with pytest.raises(HttpRequestError):
            await client.mark_thread_read("42")

        assert len(self._calls(client)) == 1

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        """An HTTP error status raises through the response's own check."""
        client = self._client(
            self._page([self._msg("new")]), HttpResponse(status_code=500, data=None)
        )

        with pytest.raises(AulaServerError):
            await client.mark_thread_read("42")

    @pytest.mark.asyncio
    async def test_network_error_propagates(self):
        """A failed connection is not swallowed."""
        client = self._client(
            self._page([self._msg("new")]), AulaConnectionError("down", status_code=0)
        )

        with pytest.raises(AulaConnectionError):
            await client.mark_thread_read("42")

    @pytest.mark.asyncio
    async def test_unconfirmed_marker_is_not_success(self):
        """The write counts only when Aula reports the marker on that message."""
        client = self._client(
            self._page([self._msg("new")]),
            self._ok(),
            self._page([], last_read="old"),
        )

        with pytest.raises(HttpRequestError, match="did not confirm"):
            await client.mark_thread_read("42")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "owner",
        [
            {"mailBoxOwnerType": "commonInbox", "id": 9},
            {"mailBoxOwnerType": "otpInbox", "id": 9},
            {"mailBoxOwnerType": None},
            {"id": 1},
            {},
            None,
            "institutionProfile",
            [],
            MISSING,
        ],
    )
    async def test_mailbox_not_shown_to_be_the_guardians_own_is_refused(self, owner):
        """The inbox IDs are sent as null, so a mailbox not shown to be the own one is refused."""
        client = self._client(self._page([self._msg("new")], owner=owner))

        with pytest.raises(ValueError, match="not shown to be in your own mailbox"):
            await client.mark_thread_read("42")

        assert len(self._calls(client)) == 1

    @pytest.mark.asyncio
    async def test_urls_follow_an_api_version_bump_between_calls(self):
        """A version negotiated by the first request is used by paging and the check."""
        client = AulaApiClient(http_client=AsyncMock(), access_token="test_token")
        old_url = client.api_url
        new_url = old_url.replace(old_url.split("/v")[-1], str(int(old_url.split("/v")[-1]) + 1))
        answers = iter(
            [
                self._page([self._msg("event", "RecipientsAdded")], more=True),
                self._page([self._msg("msg")]),
                self._ok(),
                self._page([], last_read="msg"),
            ]
        )
        seen: list[str] = []

        async def request(method, url, **kwargs):
            seen.append(url)
            if len(seen) == 1:
                client.api_url = new_url  # what a 410 answer does inside the real request
            return next(answers)

        client._request_with_version_retry = request

        assert await client.mark_thread_read("42") is True

        assert seen[0].startswith(old_url + "?")
        assert all(url.startswith(new_url + "?") for url in seen[1:])

    @pytest.mark.asyncio
    async def test_marks_deleted_and_auto_reply_messages(self):
        """The web client accepts these types as the newest message too."""
        for message_type in ("MessageDeleted", "AutoReply"):
            client = self._client(
                self._page([self._msg("last", message_type)]),
                self._ok(),
                self._page([], last_read="last"),
            )

            assert await client.mark_thread_read("42") is True
            assert self._calls(client)[1][2]["json"]["messageId"] == "last"

    @pytest.mark.asyncio
    async def test_page_limit_is_an_error_not_no_messages(self, monkeypatch):
        """Events on every permitted page, with more to come, are not 'nothing to mark'."""
        monkeypatch.setattr("aula.api_client._MAX_THREAD_PAGES", 3)
        client = self._client(
            *[self._page([self._msg(f"e{i}", "RecipientsAdded")], more=True) for i in range(3)]
        )

        with pytest.raises(ThreadScanLimitError, match="first 3 pages"):
            await client.mark_thread_read("42")

        assert len(self._calls(client)) == 3

    @pytest.mark.asyncio
    async def test_message_on_the_last_permitted_page_is_found(self, monkeypatch):
        """The cap is inclusive: the last page allowed is still read."""
        monkeypatch.setattr("aula.api_client._MAX_THREAD_PAGES", 3)
        client = self._client(
            self._page([self._msg("e0", "RecipientsAdded")], more=True),
            self._page([self._msg("e1", "RecipientsAdded")], more=True),
            self._page([self._msg("msg")], more=True),
            self._ok(),
            self._page([], last_read="msg"),
        )

        assert await client.mark_thread_read("42") is True

    @pytest.mark.asyncio
    async def test_exhausted_event_only_thread_is_false(self, monkeypatch):
        """Only events, and Aula says there are no more pages: nothing to mark."""
        monkeypatch.setattr("aula.api_client._MAX_THREAD_PAGES", 3)
        client = self._client(
            self._page([self._msg("e0", "RecipientsAdded")], more=True),
            self._page([self._msg("e1", "RecipientsAdded")], more=False),
        )

        assert await client.mark_thread_read("42") is False


class TestSkippedItemsDoNotLogPayloads:
    """Warnings and errors name what was wrong, never the names inside the item."""

    @pytest.fixture
    def client(self):
        return AulaApiClient(http_client=AsyncMock(), access_token="test_token")

    @staticmethod
    def _answer(client, data):
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data=data)
        )

    @staticmethod
    def _assert_no_names(caplog):
        records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert records
        assert all("Barn Et" not in r.getMessage() for r in records)
        assert all("Barn Et" not in str(r.args) for r in records)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "args", "data"),
        [
            ("get_group_members", (1,), {"data": [{"name": "Barn Et"}, "Barn Et"]}),
            ("get_groups", (None, [1]), {"data": [{"groups": [{"name": "Barn Et"}]}]}),
            ("get_groups", (None, [1]), {"data": [{"groups": [{"id": "x", "name": "Barn Et"}]}]}),
            ("get_posts", ([1],), {"data": {"posts": [{"title": "Barn Et"}, "Barn Et"]}}),
            (
                "get_posts",
                ([1],),
                {"data": {"posts": [{"id": "x", "title": "Barn Et", "timestamp": "Barn Et"}]}},
            ),
            ("get_comments", ("post", 1), {"data": ["Barn Et", {"id": "x", "name": "Barn Et"}]}),
            (
                "get_widgets",
                (),
                {"data": {"pageConfiguration": {"widgetConfigurations": ["Barn Et"]}}},
            ),
        ],
    )
    async def test_invalid_items_are_logged_by_shape(self, client, caplog, method, args, data):
        self._answer(client, data)

        with caplog.at_level(logging.WARNING, logger="aula"):
            try:
                await getattr(client, method)(*args)
            except AulaResponseError as e:
                assert "Barn Et" not in str(e)

        self._assert_no_names(caplog)

    @pytest.mark.asyncio
    async def test_unexpected_calendar_data_is_reported_by_type(self, client, caplog):
        self._answer(client, {"data": {"name": "Barn Et"}})
        day = datetime(2026, 1, 5, tzinfo=UTC)

        with (
            caplog.at_level(logging.WARNING, logger="aula"),
            pytest.raises(AulaResponseError) as raised,
        ):
            await client.get_calendar_events([1], day, day)

        assert "Barn Et" not in str(raised.value)
        assert all("Barn Et" not in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_the_skipped_item_is_kept_for_debug(self, client, caplog):
        self._answer(client, {"data": [{"name": "Barn Et"}]})

        with (
            caplog.at_level(logging.DEBUG, logger="aula"),
            pytest.raises(AulaResponseError),
        ):
            await client.get_group_members(1)

        debug = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("Barn Et" in r.getMessage() for r in debug)
