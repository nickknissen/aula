"""Tests for aula.api_client."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aula.api_client import AulaApiClient
from aula.http import (
    AulaAuthenticationError,
    AulaServerError,
    HttpResponse,
)


class TestRequestWithVersionRetry:
    """Tests for AulaApiClient._request_with_version_retry method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_successful_request(self, client):
        """Normal 200 response is returned directly."""
        client._client.request = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"ok": True})
        )
        resp = await client._request_with_version_retry(
            "get", "https://www.aula.dk/api/v22?method=test"
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_410_bumps_version_and_retries(self, client):
        """410 Gone triggers version bump and retry."""
        client._client.request = AsyncMock(
            side_effect=[
                HttpResponse(status_code=410, data=None),
                HttpResponse(status_code=200, data={"ok": True}),
            ]
        )
        resp = await client._request_with_version_retry(
            "get", "https://www.aula.dk/api/v22?method=test"
        )
        assert resp.status_code == 200
        assert client.api_url == "https://www.aula.dk/api/v23"

    @pytest.mark.asyncio
    async def test_multiple_410_bumps(self, client):
        """Multiple 410s bump version each time."""
        client._client.request = AsyncMock(
            side_effect=[
                HttpResponse(status_code=410, data=None),
                HttpResponse(status_code=410, data=None),
                HttpResponse(status_code=200, data={"ok": True}),
            ]
        )
        resp = await client._request_with_version_retry(
            "get", "https://www.aula.dk/api/v22?method=test"
        )
        assert resp.status_code == 200
        assert client.api_url == "https://www.aula.dk/api/v24"

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises_runtime_error(self, client):
        """5 consecutive 410s raises RuntimeError."""
        client._client.request = AsyncMock(
            return_value=HttpResponse(status_code=410, data=None)
        )
        with pytest.raises(RuntimeError, match="Failed to find working API version"):
            await client._request_with_version_retry(
                "get", "https://www.aula.dk/api/v22?method=test"
            )
        assert client._client.request.call_count == 5

    @pytest.mark.asyncio
    async def test_non_410_error_returned_without_retry(self, client):
        """Non-410 errors are returned immediately, not retried."""
        client._client.request = AsyncMock(
            return_value=HttpResponse(status_code=500, data=None)
        )
        resp = await client._request_with_version_retry(
            "get", "https://www.aula.dk/api/v22?method=test"
        )
        assert resp.status_code == 500
        assert client._client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_access_token_appended_to_url(self, client):
        """Access token is appended as query parameter for Aula API URLs."""
        client._client.request = AsyncMock(
            return_value=HttpResponse(status_code=200, data=None)
        )
        await client._request_with_version_retry(
            "get", "https://www.aula.dk/api/v22?method=test"
        )
        called_url = client._client.request.call_args[0][1]
        assert "access_token=test_token" in called_url

    @pytest.mark.asyncio
    async def test_access_token_not_appended_for_external_urls(self, client):
        """Access token is NOT appended for non-Aula URLs."""
        client._client.request = AsyncMock(
            return_value=HttpResponse(status_code=200, data=None)
        )
        await client._request_with_version_retry(
            "get", "https://api.minuddannelse.net/aula/endpoint"
        )
        called_url = client._client.request.call_args[0][1]
        assert "access_token" not in called_url

    @pytest.mark.asyncio
    async def test_access_token_added_to_params_without_mutating_original(self, client):
        """When params dict is provided, access_token is sent but original dict is not mutated."""
        client._client.request = AsyncMock(
            return_value=HttpResponse(status_code=200, data=None)
        )
        params = {"key": "value"}
        await client._request_with_version_retry(
            "get", "https://www.aula.dk/api/v22?method=test", params=params
        )
        # Original dict must NOT be mutated
        assert "access_token" not in params
        # Token must be passed in the request call
        called_params = client._client.request.call_args[1]["params"]
        assert called_params["access_token"] == "test_token"
        assert called_params["key"] == "value"


class TestGetProfile:
    """Tests for AulaApiClient.get_profile method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        c = AulaApiClient(http_client=http_client, access_token="test_token")
        return c

    def _make_profile_response(self, profiles):
        return HttpResponse(status_code=200, data={"data": {"profiles": profiles}})

    @pytest.mark.asyncio
    async def test_get_profile_happy_path(self, client):
        """Valid profile response is parsed correctly."""
        profile_data = {
            "profileId": 123,
            "displayName": "John Doe",
            "children": [
                {
                    "id": 456,
                    "profileId": 789,
                    "name": "Jane Doe",
                    "institutionProfiles": [
                        {"id": 456, "institutionName": "School A"}
                    ],
                }
            ],
            "institutionProfiles": [{"id": 100}],
        }
        client._request_with_version_retry = AsyncMock(
            return_value=self._make_profile_response([profile_data])
        )
        profile = await client.get_profile()
        assert profile.profile_id == 123
        assert profile.display_name == "John Doe"
        assert len(profile.children) == 1
        assert profile.children[0].id == 456

    @pytest.mark.asyncio
    async def test_get_profile_empty_profiles_raises(self, client):
        """Empty profiles list raises ValueError."""
        client._request_with_version_retry = AsyncMock(
            return_value=self._make_profile_response([])
        )
        with pytest.raises(ValueError, match="No profile data found"):
            await client.get_profile()

    @pytest.mark.asyncio
    async def test_get_profile_no_children(self, client):
        """Profile with no children returns empty children list."""
        profile_data = {
            "profileId": 123,
            "displayName": "John Doe",
            "children": [],
            "institutionProfiles": [],
        }
        client._request_with_version_retry = AsyncMock(
            return_value=self._make_profile_response([profile_data])
        )
        profile = await client.get_profile()
        assert profile.children == []

    @pytest.mark.asyncio
    async def test_get_profile_malformed_child_skipped(self, client):
        """Malformed child entry is skipped with warning."""
        profile_data = {
            "profileId": 123,
            "displayName": "John Doe",
            "children": [
                "not a dict",
                {
                    "id": 456,
                    "profileId": 789,
                    "name": "Jane Doe",
                    "institutionProfiles": [
                        {"id": 456, "institutionName": "School A"}
                    ],
                },
            ],
            "institutionProfiles": [],
        }
        client._request_with_version_retry = AsyncMock(
            return_value=self._make_profile_response([profile_data])
        )
        profile = await client.get_profile()
        assert len(profile.children) == 1

    @pytest.mark.asyncio
    async def test_get_profile_http_401_raises_auth_error(self, client):
        """401 response raises AulaAuthenticationError."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=401, data=None)
        )
        with pytest.raises(AulaAuthenticationError):
            await client.get_profile()

    @pytest.mark.asyncio
    async def test_get_profile_http_500_raises_server_error(self, client):
        """500 response raises AulaServerError."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=500, data=None)
        )
        with pytest.raises(AulaServerError):
            await client.get_profile()


class TestIsLoggedIn:
    """Tests for AulaApiClient.is_logged_in method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_is_logged_in_returns_true(self, client):
        """Returns True when get_profile succeeds."""
        profile_data = {
            "profileId": 123,
            "displayName": "John",
            "children": [],
            "institutionProfiles": [],
        }
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={"data": {"profiles": [profile_data]}},
            )
        )
        assert await client.is_logged_in() is True

    @pytest.mark.asyncio
    async def test_is_logged_in_returns_false_on_error(self, client):
        """Returns False when get_profile raises any exception."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=401, data=None)
        )
        assert await client.is_logged_in() is False


class TestGetDailyOverview:
    """Tests for AulaApiClient.get_daily_overview method."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_happy_path(self, client):
        """Valid daily overview response is parsed."""
        overview_data = {
            "status": 1,
            "institutionProfile": {
                "id": 456,
                "institutionName": "School A",
            },
        }
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200, data={"data": [overview_data]}
            )
        )
        result = await client.get_daily_overview(456)
        assert result is not None
        assert result.status is not None

    @pytest.mark.asyncio
    async def test_empty_data_returns_none(self, client):
        """Empty data returns None."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        result = await client.get_daily_overview(456)
        assert result is None

    @pytest.mark.asyncio
    async def test_null_data_returns_none(self, client):
        """Null data returns None."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": None})
        )
        result = await client.get_daily_overview(456)
        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_raises(self, client):
        """HTTP errors are raised."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=500, data=None)
        )
        with pytest.raises(AulaServerError):
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
    async def test_empty_threads(self, client):
        """Empty threads list returns empty."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200, data={"data": {"threads": []}}
            )
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


class TestGetPresenceTemplates:
    """Tests for AulaApiClient.get_presence_templates method."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock API client."""
        http_client = AsyncMock()
        client = AulaApiClient(
            http_client=http_client,
            access_token="test_token",
        )
        return client

    @pytest.mark.asyncio
    async def test_get_presence_templates_happy_path(self, mock_client):
        """Test fetching presence templates with valid data."""
        from aula.models.presence_template import PresenceWeekTemplate

        response_data = {
            "data": {
                "presenceWeekTemplates": [
                    {
                        "institutionProfile": {
                            "id": 10,
                            "profileId": 99,
                            "institutionName": "School",
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
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10, 20],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert len(result) == 1
        assert isinstance(result[0], PresenceWeekTemplate)
        assert result[0].institution_profile is not None
        assert result[0].institution_profile.id == 10
        assert len(result[0].day_templates) == 1
        assert result[0].day_templates[0].by_date == "2026-02-25"

    @pytest.mark.asyncio
    async def test_get_presence_templates_empty_list(self, mock_client):
        """Test fetching with empty templates list."""
        response_data = {
            "data": {
                "presenceWeekTemplates": []
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_null_data(self, mock_client):
        """Test handling when data field is null."""
        response_data = {
            "data": None
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_null_presenceWeekTemplates(self, mock_client):
        """Test handling when presenceWeekTemplates is null."""
        response_data = {
            "data": {
                "presenceWeekTemplates": None
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_null_items_in_list(self, mock_client):
        """Test handling when list contains null items."""
        response_data = {
            "data": {
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
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10, 20],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        # Should skip the null item and return 2 valid templates
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_presence_templates_malformed_item(self, mock_client, caplog):
        """Test handling of malformed template item."""
        response_data = {
            "data": {
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
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        with caplog.at_level("WARNING"):
            result = await mock_client.get_presence_templates(
                [10, 20, 30],
                date(2026, 2, 25),
                date(2026, 2, 25),
            )

        # Should return valid templates and skip/log the malformed one
        assert len(result) >= 2  # At least the two valid ones

    @pytest.mark.asyncio
    async def test_get_presence_templates_non_dict_presenceWeekTemplates(self, mock_client):
        """Test handling when presenceWeekTemplates is not a list."""
        response_data = {
            "data": {
                "presenceWeekTemplates": "not a list"
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_string_data(self, mock_client):
        """Test handling when data is a string instead of dict."""
        response_data = {
            "data": "string instead of dict"
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_non_dict_items(self, mock_client):
        """Test handling when list contains non-dict items."""
        response_data = {
            "data": {
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
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
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
    async def test_get_all_message_threads_respects_max_pages(self, client):
        """get_all_message_threads stops at MAX_PAGES."""
        # Return threads with recent dates so cutoff never triggers
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "threads": [
                            {"id": "t1", "lastMessageDate": "2026-12-01T00:00:00"}
                        ]
                    }
                },
            )
        )

        with patch("aula.api_client.MAX_PAGES", 3):
            result = await client.get_all_message_threads(date(2020, 1, 1))

        assert client._request_with_version_retry.call_count == 3
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_all_messages_for_thread_respects_max_pages(self, client):
        """get_all_messages_for_thread stops at MAX_PAGES."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "messages": [{"id": "m1", "text": "hello"}]
                    }
                },
            )
        )

        with patch("aula.api_client.MAX_PAGES", 3):
            result = await client.get_all_messages_for_thread("t1")

        assert client._request_with_version_retry.call_count == 3
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_search_messages_respects_max_pages(self, client):
        """search_messages stops at MAX_PAGES."""
        # Return results that never exhaust totalSize so pagination continues
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "results": [
                            {"id": "m1", "text": {"html": "<p>hi</p>"}}
                        ],
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

        assert client._request_with_version_retry.call_count == 3
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_all_message_threads_stops_on_empty(self, client):
        """get_all_message_threads stops when no threads returned (before MAX_PAGES)."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                HttpResponse(
                    status_code=200,
                    data={
                        "data": {
                            "threads": [
                                {"id": "t1", "lastMessageDate": "2026-12-01T00:00:00"}
                            ]
                        }
                    },
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
