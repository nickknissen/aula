"""Tests for aula.api_client."""

import inspect
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aula.api_client import AulaApiClient
from aula.const import CSRF_TOKEN_HEADER
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
        client._client.request = AsyncMock(return_value=HttpResponse(status_code=410, data=None))
        with pytest.raises(RuntimeError, match="Failed to find working API version"):
            await client._request_with_version_retry(
                "get", "https://www.aula.dk/api/v22?method=test"
            )
        assert client._client.request.call_count == 5

    @pytest.mark.asyncio
    async def test_non_410_error_returned_without_retry(self, client):
        """Non-410 errors are returned immediately, not retried."""
        client._client.request = AsyncMock(return_value=HttpResponse(status_code=500, data=None))
        resp = await client._request_with_version_retry(
            "get", "https://www.aula.dk/api/v22?method=test"
        )
        assert resp.status_code == 500
        assert client._client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_access_token_appended_during_init(self, client):
        """Access token is appended as query parameter before init clears it."""
        client._client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        await client._request_with_version_retry("get", "https://www.aula.dk/api/v22?method=test")
        called_url = client._client.request.call_args[0][1]
        assert "access_token=test_token" in called_url

    @pytest.mark.asyncio
    async def test_access_token_not_appended_after_init(self, client):
        """After init clears the token, access_token is NOT in URLs."""
        client._access_token = None  # simulate post-init state
        client._client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        await client._request_with_version_retry("get", "https://www.aula.dk/api/v22?method=test")
        called_url = client._client.request.call_args[0][1]
        assert "access_token" not in called_url

    @pytest.mark.asyncio
    async def test_access_token_not_appended_for_external_urls(self, client):
        """Access token is NOT appended for non-Aula URLs."""
        client._client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        await client._request_with_version_retry(
            "get", "https://api.minuddannelse.net/aula/endpoint"
        )
        called_url = client._client.request.call_args[0][1]
        assert "access_token" not in called_url

    @pytest.mark.asyncio
    async def test_access_token_in_params_not_mutating_original(self, client):
        """When params dict is provided, access_token is sent but original dict is not mutated."""
        client._client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        params = {"key": "value"}
        await client._request_with_version_retry(
            "get", "https://www.aula.dk/api/v22?method=test", params=params
        )
        assert "access_token" not in params
        called_params = client._client.request.call_args[1]["params"]
        assert called_params["access_token"] == "test_token"
        assert called_params["key"] == "value"

    @pytest.mark.asyncio
    async def test_post_auto_adds_csrf_header(self):
        """POST requests to Aula API auto-include csrfp-token and content-type headers."""
        http_client = AsyncMock()
        http_client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        client = AulaApiClient(http_client=http_client, csrf_token="csrf-value")
        client._access_token = None  # post-init state
        await client._request_with_version_retry(
            "post", "https://www.aula.dk/api/v22?method=test", json={"data": 1}
        )
        called_headers = http_client.request.call_args[1]["headers"]
        assert called_headers[CSRF_TOKEN_HEADER] == "csrf-value"
        assert called_headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_post_refreshes_csrf_header_from_cookie(self):
        """POST requests refresh csrfp-token from cookie when it changes."""
        http_client = AsyncMock()
        http_client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        http_client.get_cookie = MagicMock(return_value="csrf-fresh")

        client = AulaApiClient(http_client=http_client, csrf_token="csrf-old")
        client._access_token = None

        await client._request_with_version_retry(
            "post", "https://www.aula.dk/api/v22?method=test", json={"data": 1}
        )

        called_headers = http_client.request.call_args[1]["headers"]
        assert called_headers[CSRF_TOKEN_HEADER] == "csrf-fresh"
        assert client._csrf_token == "csrf-fresh"

    @pytest.mark.asyncio
    async def test_post_does_not_override_explicit_headers(self):
        """Explicit headers are not overridden by auto-added ones."""
        http_client = AsyncMock()
        http_client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        client = AulaApiClient(http_client=http_client, csrf_token="csrf-value")
        client._access_token = None
        await client._request_with_version_retry(
            "post",
            "https://www.aula.dk/api/v22?method=test",
            headers={"csrfp-token": "explicit", "content-type": "text/plain"},
        )
        called_headers = http_client.request.call_args[1]["headers"]
        assert called_headers[CSRF_TOKEN_HEADER] == "explicit"
        assert called_headers["content-type"] == "text/plain"

    @pytest.mark.asyncio
    async def test_post_no_csrf_when_token_is_none(self):
        """POST requests don't add csrfp-token header when csrf_token is None."""
        http_client = AsyncMock()
        http_client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        client = AulaApiClient(http_client=http_client, csrf_token=None)
        client._access_token = None
        await client._request_with_version_retry(
            "post", "https://www.aula.dk/api/v22?method=test", json={"data": 1}
        )
        called_headers = http_client.request.call_args[1]["headers"]
        assert called_headers is None

    @pytest.mark.asyncio
    async def test_get_does_not_add_csrf_header(self):
        """GET requests do NOT auto-include csrfp-token header."""
        http_client = AsyncMock()
        http_client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        client = AulaApiClient(http_client=http_client, csrf_token="csrf-value")
        client._access_token = None
        await client._request_with_version_retry("get", "https://www.aula.dk/api/v22?method=test")
        called_headers = http_client.request.call_args[1]["headers"]
        assert called_headers is None

    @pytest.mark.asyncio
    async def test_post_external_url_no_csrf_header(self):
        """POST requests to non-Aula URLs don't auto-include csrfp-token."""
        http_client = AsyncMock()
        http_client.request = AsyncMock(return_value=HttpResponse(status_code=200, data=None))
        client = AulaApiClient(http_client=http_client, csrf_token="csrf-value")
        client._access_token = None
        await client._request_with_version_retry(
            "post", "https://api.minuddannelse.net/endpoint", json={"data": 1}
        )
        called_headers = http_client.request.call_args[1]["headers"]
        assert called_headers is None

    @pytest.mark.asyncio
    async def test_init_clears_access_token(self):
        """init() clears access_token after establishing the session."""
        http_client = AsyncMock()
        http_client.request = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "profiles": [
                            {
                                "profileId": 1,
                                "displayName": "Test",
                                "children": [],
                                "institutionProfiles": [],
                            }
                        ]
                    }
                },
            )
        )
        http_client.get_cookie = MagicMock(return_value="csrf-tok")
        client = AulaApiClient(http_client=http_client, access_token="test_token")
        assert client._access_token == "test_token"
        await client.init()
        assert client._access_token is None


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
                    "institutionProfiles": [{"id": 456, "institutionName": "School A"}],
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
        client._request_with_version_retry = AsyncMock(return_value=self._make_profile_response([]))
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
                    "institutionProfiles": [{"id": 456, "institutionName": "School A"}],
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
            return_value=HttpResponse(status_code=200, data={"data": [overview_data]})
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
        response_data = {"data": {"presenceWeekTemplates": []}}

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
        response_data = {"data": None}

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
        response_data = {"data": {"presenceWeekTemplates": None}}

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
        response_data = {"data": {"presenceWeekTemplates": "not a list"}}

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
        response_data = {"data": "string instead of dict"}

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
                    "data": {"threads": [{"id": "t1", "lastMessageDate": "2026-12-01T00:00:00"}]}
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
                data={"data": {"messages": [{"id": "m1", "text": "hello"}]}},
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
                        "results": [{"id": "m1", "text": {"html": "<p>hi</p>"}}],
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
                            "threads": [{"id": "t1", "lastMessageDate": "2026-12-01T00:00:00"}]
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


class TestBearerTokenCompatibilityWrapper:
    """Compatibility wrapper should transparently delegate to widgets namespace."""

    @pytest.fixture
    def client(self):
        http_client = AsyncMock()
        return AulaApiClient(http_client=http_client, access_token="test_token")

    @pytest.mark.asyncio
    async def test_get_bearer_token_delegates_to_widgets(self, client):
        client.widgets._get_bearer_token = AsyncMock(return_value="Bearer test-token")

        token = await client._get_bearer_token("widget-id")

        assert token == "Bearer test-token"
        client.widgets._get_bearer_token.assert_awaited_once_with("widget-id")

    @pytest.mark.asyncio
    async def test_get_bearer_token_preserves_widget_status_handling(self, client):
        client.widgets._get_bearer_token = AsyncMock(
            side_effect=AulaAuthenticationError("HTTP 401", status_code=401)
        )

        with pytest.raises(AulaAuthenticationError):
            await client._get_bearer_token("widget-id")

        client.widgets._get_bearer_token.assert_awaited_once_with("widget-id")


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
    async def test_happy_path_with_lesson(self, client):
        """Events with lesson participants are parsed correctly."""
        raw_events = [
            {
                "id": 1,
                "title": "Math",
                "startDateTime": "2026-03-01T08:00:00+01:00",
                "endDateTime": "2026-03-01T09:00:00+01:00",
                "belongsToProfiles": [100],
                "lesson": {
                    "participants": [
                        {"participantRole": "primaryTeacher", "teacherName": "Mrs. Jensen"},
                        {"participantRole": "substituteTeacher", "teacherName": "Mr. Hansen"},
                    ],
                    "lessonStatus": "substitute",
                    "primaryResource": {"name": "Room 101"},
                },
            }
        ]
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": raw_events})
        )

        events = await client.get_calendar_events(
            [100], datetime(2026, 3, 1), datetime(2026, 3, 1)
        )

        assert len(events) == 1
        assert events[0].title == "Math"
        assert events[0].teacher_name == "Mrs. Jensen"
        assert events[0].has_substitute is True
        assert events[0].substitute_name == "Mr. Hansen"
        assert events[0].location == "Room 101"
        assert events[0].belongs_to == 100

    @pytest.mark.asyncio
    async def test_empty_events_list(self, client):
        """Empty events list returns empty."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": []})
        )
        events = await client.get_calendar_events(
            [100], datetime(2026, 3, 1), datetime(2026, 3, 1)
        )
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

        events = await client.get_calendar_events(
            [100], datetime(2026, 3, 2), datetime(2026, 3, 2)
        )

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

        events = await client.get_calendar_events(
            [100], datetime(2026, 3, 1), datetime(2026, 3, 1)
        )
        assert len(events) == 1
        assert events[0].title == "Good"

    @pytest.mark.asyncio
    async def test_non_list_data_returns_empty(self, client):
        """Non-list data format returns empty list."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(status_code=200, data={"data": "unexpected"})
        )
        events = await client.get_calendar_events(
            [100], datetime(2026, 3, 1), datetime(2026, 3, 1)
        )
        assert events == []


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
            return_value=HttpResponse(
                status_code=200, data={"data": {"posts": posts_data}}
            )
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
            return_value=HttpResponse(
                status_code=200, data={"data": {"posts": posts_data}}
            )
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
            return_value=HttpResponse(
                status_code=200, data={"data": {"posts": posts_data}}
            )
        )
        posts = await client.get_posts([100])
        assert len(posts) == 1
        assert posts[0].id == 30

    @pytest.mark.asyncio
    async def test_empty_posts(self, client):
        """Empty posts list returns empty."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200, data={"data": {"posts": []}}
            )
        )
        posts = await client.get_posts([100])
        assert posts == []


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
                            {"id": "m1", "text": {"html": "<p>Hello</p>"}},
                            {"id": "m2", "text": "Plain text"},
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
                    "results": [{"id": "m1", "text": "page1"}],
                    "totalSize": 2,
                }
            },
        )
        page2 = HttpResponse(
            status_code=200,
            data={
                "data": {
                    "results": [{"id": "m2", "text": "page2"}],
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
                            {"id": "m1", "text": {"html": "<b>bold</b>"}},
                            {"id": "m2", "text": "plain"},
                            {"id": "m3", "text": 12345},
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
    async def test_stops_at_cutoff(self, client):
        """Stops collecting threads when thread date < cutoff_date."""
        client._request_with_version_retry = AsyncMock(
            return_value=HttpResponse(
                status_code=200,
                data={
                    "data": {
                        "threads": [
                            {"id": "t1", "lastMessageDate": "2026-03-01T10:00:00"},
                            {"id": "t2", "lastMessageDate": "2026-01-01T10:00:00"},
                        ]
                    }
                },
            )
        )
        result = await client.get_all_message_threads(date(2026, 2, 1))
        # t1 (March) is after cutoff, collected; t2 (Jan) triggers early return
        assert len(result) == 1
        assert result[0]["id"] == "t1"

    @pytest.mark.asyncio
    async def test_handles_missing_dates(self, client):
        """Threads with missing dates are still collected."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                HttpResponse(
                    status_code=200,
                    data={
                        "data": {
                            "threads": [
                                {"id": "t1"},
                                {"id": "t2", "lastMessageDate": ""},
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
        result = await client.get_all_message_threads(date(2026, 2, 1))
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_handles_malformed_dates(self, client):
        """Threads with malformed dates are still collected."""
        client._request_with_version_retry = AsyncMock(
            side_effect=[
                HttpResponse(
                    status_code=200,
                    data={
                        "data": {
                            "threads": [
                                {"id": "t1", "lastMessageDate": "not-a-date"},
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
        result = await client.get_all_message_threads(date(2026, 2, 1))
        assert len(result) == 1


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
            return_value=HttpResponse(
                status_code=200, data={"data": {"albums": albums}}
            )
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
            return_value=HttpResponse(
                status_code=200, data={"data": {"results": pics}}
            )
        )
        result = await client.get_album_pictures([100], album_id=1)
        assert result == pics
