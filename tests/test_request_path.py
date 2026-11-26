"""What every Aula call goes through: API version, refresh, new session, envelope, headers."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from aula.api_client import AulaApiClient
from aula.const import API_URL, API_VERSION, CSRF_TOKEN_HEADER
from aula.http import (
    AulaApiVersionError,
    AulaAuthenticationError,
    AulaInvalidTokenError,
    AulaLoginRequiredError,
    AulaRejectedError,
    AulaServerError,
    HttpRequestError,
)
from tests.fakes import FakeHttpClient, http_status, ok, rejected

API = f"{API_URL}{API_VERSION}"
STATES = "presence.getPresenceStates"
EVENT_TYPES = "calendar.getEventTypes"
CALENDAR = "calendar.getEventsByProfileIdsAndResourceIds"
LOGIN = "profiles.getProfilesByLogin"
CONTEXT = "profiles.getProfileContext"


class _InterleavingHttpClient(FakeHttpClient):
    """Yields before every answer, so concurrent callers really do interleave."""

    async def request(self, method, url, **kwargs):
        await asyncio.sleep(0)
        return await super().request(method, url, **kwargs)


def _session(http: FakeHttpClient) -> FakeHttpClient:
    """Answer the two calls that open a session."""
    http.aula(LOGIN, ok({"profiles": []}))
    http.aula(CONTEXT, ok({}))
    return http


def _read_calendar(client: AulaApiClient):
    """A read Aula takes as a POST."""
    return client.get_calendar_events([1000001], datetime(2026, 1, 5), datetime(2026, 1, 5))


class TestApiVersion:
    @pytest.mark.asyncio
    async def test_a_read_returns_what_aula_answered(self):
        http = FakeHttpClient()
        http.aula(STATES, ok([]))
        client = AulaApiClient(http)

        assert await client.get_presence_states() == []
        assert len(http.calls(STATES)) == 1

    @pytest.mark.asyncio
    async def test_410_moves_to_the_next_version_and_retries(self):
        http = FakeHttpClient()
        http.route(f"{API_URL}{API_VERSION}", http_status(410))
        http.route(f"{API_URL}{int(API_VERSION) + 1}", ok([]))
        client = AulaApiClient(http)

        assert await client.get_presence_states() == []
        assert client.api_url == f"{API_URL}{int(API_VERSION) + 1}"

    @pytest.mark.asyncio
    async def test_each_410_moves_one_version_further(self):
        http = FakeHttpClient()
        http.route(f"{API_URL}{API_VERSION}", http_status(410))
        http.route(f"{API_URL}{int(API_VERSION) + 1}", http_status(410))
        http.route(f"{API_URL}{int(API_VERSION) + 2}", ok([]))
        client = AulaApiClient(http)

        assert await client.get_presence_states() == []
        assert client.api_url == f"{API_URL}{int(API_VERSION) + 2}"

    @pytest.mark.asyncio
    async def test_five_410s_give_up_with_an_api_version_error(self):
        http = FakeHttpClient()
        http.route(API_URL, http_status(410))
        client = AulaApiClient(http)

        with pytest.raises(AulaApiVersionError, match="Failed to find working API version") as exc:
            await client.get_presence_states()

        assert isinstance(exc.value, HttpRequestError)
        assert exc.value.status_code == 410
        assert len(http.requests) == 5

    @pytest.mark.asyncio
    async def test_concurrent_410s_move_one_version_and_both_retry_there(self):
        http = _InterleavingHttpClient()
        http.route(f"{API_URL}25", http_status(410))
        http.route(f"{API_URL}26", ok([]))
        client = AulaApiClient(http)
        client.api_url = f"{API_URL}25"

        assert await asyncio.gather(client.get_presence_states(), client.get_event_types()) == [
            [],
            [],
        ]

        assert client.api_url == f"{API_URL}26"
        assert sorted((r.url, r.aula_method) for r in http.requests) == [
            (f"{API_URL}25", EVENT_TYPES),
            (f"{API_URL}25", STATES),
            (f"{API_URL}26", EVENT_TYPES),
            (f"{API_URL}26", STATES),
        ]

    @pytest.mark.asyncio
    async def test_other_http_errors_are_raised_without_a_retry(self):
        http = FakeHttpClient()
        http.aula(STATES, http_status(500))
        client = AulaApiClient(http)

        with pytest.raises(AulaServerError):
            await client.get_presence_states()

        assert len(http.requests) == 1


class TestRefresh:
    @pytest.mark.asyncio
    async def test_concurrent_auth_failures_share_one_refresh_and_both_replay(self):
        http = _session(_InterleavingHttpClient())
        http.cookies["Csrfp-Token"] = "csrf-token"
        http.aula(STATES, http_status(401), ok([]))
        http.aula(EVENT_TYPES, http_status(401), ok([]))

        async def refresh_token():
            while not (http.calls(STATES) and http.calls(EVENT_TYPES)):
                await asyncio.sleep(0)
            return "refreshed-token"

        on_token_refresh = AsyncMock(side_effect=refresh_token)
        client = AulaApiClient(http, on_token_refresh=on_token_refresh)

        assert await asyncio.gather(client.get_presence_states(), client.get_event_types()) == [
            [],
            [],
        ]

        on_token_refresh.assert_awaited_once_with()
        assert len(http.calls(STATES)) == 2
        assert len(http.calls(EVENT_TYPES)) == 2

    @pytest.mark.asyncio
    async def test_session_expired_sub_code_refreshes_and_replays(self):
        http = _session(FakeHttpClient())
        http.aula(STATES, http_status(200, {"status": {"subCode": 23}}), ok([]))
        on_token_refresh = AsyncMock(return_value="refreshed-token")
        client = AulaApiClient(http, on_token_refresh=on_token_refresh)

        assert await client.get_presence_states() == []

        on_token_refresh.assert_awaited_once_with()
        assert len(http.calls(STATES)) == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("answer", "original"),
        [
            (http_status(401), AulaAuthenticationError),
            (http_status(200, {"status": {"subCode": 9}}), AulaInvalidTokenError),
        ],
    )
    async def test_a_rejected_refresh_raises_login_required_from_the_original_error(
        self, answer, original
    ):
        http = FakeHttpClient()
        http.aula(STATES, answer)
        rejected_refresh = AulaLoginRequiredError("Token server rejected the refresh token", 400)
        client = AulaApiClient(
            http, access_token="old-token", on_token_refresh=AsyncMock(side_effect=rejected_refresh)
        )

        with pytest.raises(AulaLoginRequiredError) as raised:
            await client.get_presence_states()

        assert type(raised.value.__cause__) is original
        assert raised.value.status_code == 401
        assert len(http.calls(STATES)) == 1

    @pytest.mark.asyncio
    async def test_a_second_401_is_raised_without_another_refresh(self):
        http = _session(FakeHttpClient())
        http.aula(STATES, http_status(401))
        on_token_refresh = AsyncMock(return_value="refreshed-token")
        client = AulaApiClient(http, on_token_refresh=on_token_refresh)

        with pytest.raises(AulaAuthenticationError):
            await client.get_presence_states()

        on_token_refresh.assert_awaited_once_with()
        assert len(http.calls(STATES)) == 2


class TestNewSessionAfterRefusedRefresh:
    STORED_COOKIES = {"PHPSESSID": "session0001", "Csrfp-Token": "csrf-token"}
    REFUSED = rejected(10)

    @pytest.fixture
    def http(self):
        http = _session(_InterleavingHttpClient())
        http.cookies = dict(self.STORED_COOKIES)
        return http

    @pytest.fixture
    def on_token_refresh(self):
        return AsyncMock(return_value="access-2")

    @pytest.fixture
    def client(self, http, on_token_refresh):
        return AulaApiClient(
            http,
            access_token="access-1",
            on_token_refresh=on_token_refresh,
            session_cookies=self.STORED_COOKIES,
        )

    async def _refresh(self, client: AulaApiClient, http: FakeHttpClient) -> None:
        """Refresh the client without any call answered on the refreshed session yet."""
        await client.init()
        assert await client._refresh_authentication(client._auth_generation)
        http.cookies["SessionCookie"] = "received-after-login"

    @pytest.mark.asyncio
    async def test_refused_call_after_refresh_starts_one_new_session_and_replays(
        self, client, http, on_token_refresh
    ):
        await self._refresh(client, http)
        http.aula(STATES, self.REFUSED, ok([]))

        assert await client.get_presence_states() == []

        assert len(http.calls(STATES)) == 2
        on_token_refresh.assert_awaited_once_with()
        assert http.calls(LOGIN)[2].query["access_token"] == "access-2"
        assert len(http.calls(LOGIN)) == 3
        assert client._access_token is None

    @pytest.mark.asyncio
    async def test_new_session_drops_cookies_received_after_login(self, client, http):
        await self._refresh(client, http)
        http.aula(STATES, self.REFUSED, ok([]))

        await client.get_presence_states()

        assert http.cookies == self.STORED_COOKIES

    @pytest.mark.asyncio
    async def test_refused_replay_raises(self, client, http):
        await self._refresh(client, http)
        http.aula(STATES, self.REFUSED)

        with pytest.raises(AulaRejectedError) as raised:
            await client.get_presence_states()

        assert raised.value.code == 10
        assert len(http.calls(STATES)) == 2
        assert len(http.calls(LOGIN)) == 3

    @pytest.mark.asyncio
    async def test_refused_replay_of_the_refresh_starts_a_new_session(self, client, http):
        await client.init()
        http.aula(STATES, http_status(401), self.REFUSED, ok([]))

        assert await client.get_presence_states() == []

        assert len(http.calls(STATES)) == 3
        assert len(http.calls(LOGIN)) == 3

    @pytest.mark.asyncio
    async def test_refusal_without_a_refresh_raises_at_once(self, client, http):
        await client.init()
        http.aula(STATES, self.REFUSED, ok([]))

        with pytest.raises(AulaRejectedError):
            await client.get_presence_states()

        assert len(http.calls(STATES)) == 1
        assert len(http.calls(LOGIN)) == 1

    @pytest.mark.asyncio
    async def test_refusal_after_the_refreshed_session_worked_raises_at_once(self, client, http):
        await self._refresh(client, http)
        http.aula(EVENT_TYPES, ok([]))
        http.aula(STATES, self.REFUSED, ok([]))
        await client.get_event_types()

        with pytest.raises(AulaRejectedError):
            await client.get_presence_states()

        assert len(http.calls(STATES)) == 1
        assert len(http.calls(LOGIN)) == 2
        assert http.cookies["SessionCookie"] == "received-after-login"

    @pytest.mark.asyncio
    async def test_one_new_session_per_refresh(self, client, http):
        await self._refresh(client, http)
        http.aula(STATES, self.REFUSED, ok([]), self.REFUSED)
        await client.get_presence_states()

        with pytest.raises(AulaRejectedError):
            await client.get_presence_states()

        assert len(http.calls(LOGIN)) == 3

    @pytest.mark.asyncio
    async def test_concurrent_refusals_share_one_new_session(self, client, http):
        await self._refresh(client, http)
        http.aula(STATES, self.REFUSED, ok([]))
        http.aula(EVENT_TYPES, self.REFUSED, ok([]))

        assert await asyncio.gather(client.get_presence_states(), client.get_event_types()) == [
            [],
            [],
        ]
        assert len(http.calls(LOGIN)) == 3


class TestDebugLogging:
    @pytest.mark.asyncio
    async def test_names_the_method_and_logs_the_response(self, caplog):
        http = FakeHttpClient()
        http.aula(STATES, ok([]))
        client = AulaApiClient(http)

        with caplog.at_level("DEBUG"):
            await client.get_presence_states()

        messages = [r.message for r in caplog.records]
        assert any(f"method={STATES}" in m for m in messages)
        assert any(f"Response method={STATES}" in m and '"data":[]' in m for m in messages)

    @pytest.mark.asyncio
    async def test_a_non_json_error_page_raises_the_same_error_with_debug_on(self, caplog):
        http = FakeHttpClient()
        http.aula(
            STATES,
            http_status(503, headers={"Content-Type": "text/html", "Content-Length": "42"}),
        )
        client = AulaApiClient(http)

        with caplog.at_level("DEBUG"), pytest.raises(AulaServerError):
            await client.get_presence_states()

        messages = [r.message for r in caplog.records]
        assert any("content-type=text/html" in m and "length=42" in m for m in messages)

    @pytest.mark.asyncio
    async def test_an_empty_body_logs_its_content_type_and_length(self, caplog):
        http = FakeHttpClient()
        http.aula("profiles.keepAlive", http_status(204))
        client = AulaApiClient(http)

        with caplog.at_level("DEBUG"):
            assert await client.keep_alive()

        assert any("non-JSON body" in r.message for r in caplog.records)


class TestAccessToken:
    @pytest.mark.asyncio
    async def test_is_sent_until_init_finishes(self):
        http = FakeHttpClient()
        http.aula(STATES, ok([]))
        client = AulaApiClient(http, access_token="test_token")

        await client.get_presence_states()

        assert http.calls(STATES)[0].query["access_token"] == "test_token"

    @pytest.mark.asyncio
    async def test_init_opens_the_session_with_it_and_then_drops_it(self):
        http = _session(FakeHttpClient())
        http.aula(STATES, ok([]))
        client = AulaApiClient(http, access_token="test_token")

        await client.init()
        await client.get_presence_states()

        assert http.calls(LOGIN)[0].query["access_token"] == "test_token"
        assert http.calls(CONTEXT)[0].query["access_token"] == "test_token"
        assert "access_token" not in http.calls(STATES)[0].query


class TestCsrfHeader:
    @pytest.mark.asyncio
    async def test_a_post_carries_the_csrf_token_and_a_json_content_type(self):
        http = FakeHttpClient()
        http.aula(CALENDAR, ok([]))
        client = AulaApiClient(http, csrf_token="csrf-value")

        await _read_calendar(client)

        headers = http.calls(CALENDAR)[0].headers
        assert headers[CSRF_TOKEN_HEADER] == "csrf-value"
        assert headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_a_post_takes_a_newer_csrf_token_from_the_cookie(self):
        http = FakeHttpClient()
        http.cookies["Csrfp-Token"] = "csrf-fresh"
        http.aula(CALENDAR, ok([]))
        client = AulaApiClient(http, csrf_token="csrf-old")

        await _read_calendar(client)

        assert http.calls(CALENDAR)[0].headers[CSRF_TOKEN_HEADER] == "csrf-fresh"

    @pytest.mark.asyncio
    async def test_a_post_without_a_csrf_token_sends_no_csrf_header(self):
        http = FakeHttpClient()
        http.aula(CALENDAR, ok([]))
        client = AulaApiClient(http, csrf_token=None)

        await _read_calendar(client)

        assert CSRF_TOKEN_HEADER not in http.calls(CALENDAR)[0].headers

    @pytest.mark.asyncio
    async def test_a_get_sends_no_csrf_header(self):
        http = FakeHttpClient()
        http.aula(STATES, ok([]))
        client = AulaApiClient(http, csrf_token="csrf-value")

        await client.get_presence_states()

        assert CSRF_TOKEN_HEADER not in http.calls(STATES)[0].headers
