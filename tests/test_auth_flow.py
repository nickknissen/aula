"""Tests for aula.auth_flow — authenticate, create_client, authenticate_and_create_client."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aula.auth.exceptions import OAuthError
from aula.auth_flow import authenticate, authenticate_and_create_client, create_client
from aula.const import CSRF_TOKEN_COOKIE
from aula.http import AulaAuthenticationError, HttpResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile_response() -> HttpResponse:
    """Minimal valid response for get_profile / init calls."""
    return HttpResponse(
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


def _mock_http_client() -> AsyncMock:
    """Create a mock HttpClient that returns valid profile responses."""
    client = AsyncMock()
    client.request = AsyncMock(return_value=_profile_response())
    client.get_cookie = MagicMock(return_value="csrf-tok")
    client.close = AsyncMock()
    return client


def _mock_auth_client_factory():
    """Create a mock MitIDAuthClient with sane defaults."""
    auth = AsyncMock()
    auth.tokens = {"access_token": "fresh-tok"}
    auth.access_token = "fresh-tok"
    auth.cookies = {"PHPSESSID": "sess1", CSRF_TOKEN_COOKIE: "csrf1"}
    auth.authenticate = AsyncMock()
    auth.refresh_access_token = AsyncMock()
    auth.close = AsyncMock()
    auth.__aenter__ = AsyncMock(return_value=auth)
    auth.__aexit__ = AsyncMock(return_value=False)
    return auth


# ---------------------------------------------------------------------------
# create_client
# ---------------------------------------------------------------------------


class TestCreateClient:
    """Tests for the create_client factory function."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Valid token_data returns a configured AulaApiClient with token cleared after init."""
        http = _mock_http_client()
        token_data = {
            "tokens": {"access_token": "tok123"},
            "cookies": {CSRF_TOKEN_COOKIE: "csrf-tok"},
        }
        client = await create_client(token_data, http_client=http)
        # access_token is cleared after init()
        assert client._access_token is None
        assert client._csrf_token == "csrf-tok"

    @pytest.mark.asyncio
    async def test_missing_access_token_raises(self):
        """Raises ValueError when access_token is missing."""
        with pytest.raises(ValueError, match="No access_token"):
            await create_client({"tokens": {}})

    @pytest.mark.asyncio
    async def test_empty_token_data_raises(self):
        """Raises ValueError when token_data has no tokens key."""
        with pytest.raises(ValueError, match="No access_token"):
            await create_client({})

    @pytest.mark.asyncio
    async def test_creates_httpx_client_when_none(self):
        """When http_client is None, an HttpxHttpClient is created from cookies."""
        token_data = {
            "tokens": {"access_token": "tok123"},
            "cookies": {"PHPSESSID": "sess1"},
        }
        with patch("aula.auth_flow.HttpxHttpClient") as MockHttpx:
            mock_instance = _mock_http_client()
            MockHttpx.return_value = mock_instance
            client = await create_client(token_data)
            MockHttpx.assert_called_once_with(cookies={"PHPSESSID": "sess1"})
            # access_token cleared after init
            assert client._access_token is None


# ---------------------------------------------------------------------------
# authenticate (returns token_data dict)
# ---------------------------------------------------------------------------


class TestAuthenticate:
    """Tests for the authenticate function that returns raw token data."""

    @pytest.fixture
    def token_storage(self):
        storage = AsyncMock()
        storage.load = AsyncMock(return_value=None)
        storage.save = AsyncMock()
        return storage

    @pytest.fixture
    def mock_auth_client(self):
        return _mock_auth_client_factory()

    # -- Returns token_data dict --

    @pytest.mark.asyncio
    async def test_returns_token_data_dict(self, token_storage, mock_auth_client):
        """authenticate() returns a dict with tokens and cookies keys."""
        token_storage.load.return_value = None

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            result = await authenticate("user", token_storage)

        assert "tokens" in result
        assert "cookies" in result
        assert result["tokens"]["access_token"] == "fresh-tok"

    @pytest.mark.asyncio
    async def test_fresh_auth_returns_full_token_data(self, token_storage, mock_auth_client):
        """Fresh auth returns full token data including expires_at and metadata."""
        token_storage.load.return_value = None
        mock_auth_client.tokens = {
            "access_token": "fresh-tok",
            "refresh_token": "fresh-refresh",
            "expires_at": 9999999999.0,
        }

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            result = await authenticate("user", token_storage)

        assert result["tokens"]["access_token"] == "fresh-tok"
        assert result["tokens"]["refresh_token"] == "fresh-refresh"
        assert result["tokens"]["expires_at"] == 9999999999.0
        assert result["username"] == "user"
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_refresh_returns_full_token_data(self, token_storage, mock_auth_client):
        """Token refresh returns full token data including expires_at."""
        token_storage.load.return_value = {
            "tokens": {
                "access_token": "expired-tok",
                "refresh_token": "old-refresh",
                "expires_at": time.time() - 100,
            },
            "cookies": {CSRF_TOKEN_COOKIE: "csrf"},
        }
        new_tokens = {
            "access_token": "refreshed-tok",
            "refresh_token": "new-refresh",
            "expires_at": 9999999999.0,
        }
        mock_auth_client.refresh_access_token = AsyncMock(return_value=new_tokens)
        mock_auth_client.access_token = "refreshed-tok"

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            result = await authenticate("user", token_storage)

        assert result["tokens"]["access_token"] == "refreshed-tok"
        assert result["tokens"]["refresh_token"] == "new-refresh"
        assert result["tokens"]["expires_at"] == 9999999999.0
        assert result["username"] == "user"

    @pytest.mark.asyncio
    async def test_cached_returns_full_token_data(self, token_storage, mock_auth_client):
        """Cached valid tokens return full token data including expires_at."""
        cached = {
            "tokens": {
                "access_token": "cached-tok",
                "refresh_token": "cached-refresh",
                "expires_at": time.time() + 3600,
            },
            "cookies": {CSRF_TOKEN_COOKIE: "csrf"},
            "username": "user",
            "timestamp": 1234567890.0,
        }
        token_storage.load.return_value = cached
        mock_auth_client.access_token = "cached-tok"

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            result = await authenticate("user", token_storage)

        assert result["tokens"]["refresh_token"] == "cached-refresh"
        assert result["tokens"]["expires_at"] == cached["tokens"]["expires_at"]
        assert result["username"] == "user"
        assert result["timestamp"] == 1234567890.0

    # -- No token_storage → always runs full auth --

    @pytest.mark.asyncio
    async def test_no_storage_runs_full_auth(self, mock_auth_client):
        """When token_storage is None, always runs full MitID auth."""
        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            result = await authenticate("user", token_storage=None)

        mock_auth_client.authenticate.assert_awaited_once()
        assert result["tokens"]["access_token"] == "fresh-tok"

    # -- No cached tokens → full MitID flow --

    @pytest.mark.asyncio
    async def test_no_cached_tokens_runs_full_auth(self, token_storage, mock_auth_client):
        """When storage returns None, runs full MitID authentication."""
        token_storage.load.return_value = None

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            await authenticate("user", token_storage)

        mock_auth_client.authenticate.assert_awaited_once()
        token_storage.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_login_required_callback_called(self, token_storage, mock_auth_client):
        """on_login_required callback is invoked before MitID auth."""
        token_storage.load.return_value = None
        callback = MagicMock()

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            await authenticate("user", token_storage, on_login_required=callback)

        callback.assert_called_once()

    # -- Valid cached tokens → skip auth --

    @pytest.mark.asyncio
    async def test_valid_cached_tokens_skip_auth(self, token_storage, mock_auth_client):
        """When valid non-expired tokens are cached, skips MitID flow."""
        token_storage.load.return_value = {
            "tokens": {
                "access_token": "cached-tok",
                "expires_at": time.time() + 3600,
            },
            "cookies": {CSRF_TOKEN_COOKIE: "csrf-cached"},
        }
        mock_auth_client.access_token = "cached-tok"

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            result = await authenticate("user", token_storage)

        mock_auth_client.authenticate.assert_not_awaited()
        mock_auth_client.refresh_access_token.assert_not_awaited()
        assert result["tokens"]["access_token"] == "cached-tok"

    @pytest.mark.asyncio
    async def test_force_login_skips_cached_tokens(self, token_storage, mock_auth_client):
        """force_login bypasses cached credentials and runs full MitID auth."""
        token_storage.load.return_value = {
            "tokens": {"access_token": "cached-tok", "expires_at": time.time() + 3600},
            "cookies": {"PHPSESSID": "stale"},
        }
        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            result = await authenticate("user", token_storage, force_login=True)

        token_storage.load.assert_not_awaited()
        mock_auth_client.refresh_access_token.assert_not_awaited()
        mock_auth_client.authenticate.assert_awaited_once()
        assert result["tokens"]["access_token"] == "fresh-tok"

    @pytest.mark.asyncio
    async def test_cached_tokens_no_expiry_treated_as_valid(self, token_storage, mock_auth_client):
        """Tokens without expires_at are treated as valid."""
        token_storage.load.return_value = {
            "tokens": {"access_token": "no-expiry-tok"},
            "cookies": {},
        }
        mock_auth_client.access_token = "no-expiry-tok"

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            await authenticate("user", token_storage)

        mock_auth_client.authenticate.assert_not_awaited()

    # -- Expired tokens with refresh_token → refresh --

    @pytest.mark.asyncio
    async def test_expired_tokens_refresh_succeeds(self, token_storage, mock_auth_client):
        """Expired tokens with refresh_token triggers refresh flow."""
        token_storage.load.return_value = {
            "tokens": {
                "access_token": "expired-tok",
                "refresh_token": "refresh-tok",
                "expires_at": time.time() - 100,
            },
            "cookies": {CSRF_TOKEN_COOKIE: "csrf-old"},
        }
        new_tokens = {"access_token": "refreshed-tok", "refresh_token": "new-refresh"}
        mock_auth_client.refresh_access_token = AsyncMock(return_value=new_tokens)
        mock_auth_client.access_token = "refreshed-tok"

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            await authenticate("user", token_storage)

        mock_auth_client.refresh_access_token.assert_awaited_once_with("refresh-tok")
        mock_auth_client.authenticate.assert_not_awaited()
        token_storage.save.assert_awaited_once()

    # -- Refresh fails → falls back to full auth --

    @pytest.mark.asyncio
    async def test_refresh_failure_falls_back_to_full_auth(self, token_storage, mock_auth_client):
        """When refresh fails, falls back to full MitID authentication."""
        token_storage.load.return_value = {
            "tokens": {
                "access_token": "expired-tok",
                "refresh_token": "bad-refresh",
                "expires_at": time.time() - 100,
            },
            "cookies": {},
        }
        mock_auth_client.refresh_access_token = AsyncMock(side_effect=OAuthError("refresh failed"))

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            await authenticate("user", token_storage)

        mock_auth_client.authenticate.assert_awaited_once()

    # -- Expired tokens, no refresh_token → full auth --

    @pytest.mark.asyncio
    async def test_expired_no_refresh_token_runs_full_auth(self, token_storage, mock_auth_client):
        """Expired tokens without refresh_token triggers full MitID auth."""
        token_storage.load.return_value = {
            "tokens": {
                "access_token": "expired-tok",
                "expires_at": time.time() - 100,
            },
            "cookies": {},
        }

        with patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client):
            await authenticate("user", token_storage)

        mock_auth_client.authenticate.assert_awaited_once()

    # -- Auth fails → RuntimeError --

    @pytest.mark.asyncio
    async def test_auth_failure_raises_runtime_error(self, token_storage, mock_auth_client):
        """MitID authentication failure raises RuntimeError."""
        from aula.auth.exceptions import MitIDAuthError as AuthExc

        token_storage.load.return_value = None
        mock_auth_client.authenticate = AsyncMock(side_effect=AuthExc("MitID timeout"))

        with (
            patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client),
            pytest.raises(RuntimeError, match="MitID authentication failed"),
        ):
            await authenticate("user", token_storage)

    # -- No access_token after auth → RuntimeError --

    @pytest.mark.asyncio
    async def test_no_access_token_after_auth_raises(self, token_storage, mock_auth_client):
        """Raises RuntimeError if no access_token is available after auth."""
        token_storage.load.return_value = None
        mock_auth_client.access_token = None

        with (
            patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client),
            pytest.raises(RuntimeError, match="No access token available"),
        ):
            await authenticate("user", token_storage)


# ---------------------------------------------------------------------------
# authenticate_and_create_client (convenience wrapper)
# ---------------------------------------------------------------------------


class TestAuthenticateAndCreateClient:
    """Tests for the convenience wrapper that returns an AulaApiClient."""

    @pytest.fixture
    def token_storage(self):
        storage = AsyncMock()
        storage.load = AsyncMock(return_value=None)
        storage.save = AsyncMock()
        return storage

    @pytest.fixture
    def mock_auth_client(self):
        return _mock_auth_client_factory()

    @pytest.mark.asyncio
    async def test_calls_authenticate_then_create_client(self, token_storage, mock_auth_client):
        """authenticate_and_create_client delegates to authenticate + create_client."""
        with (
            patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client),
            patch("aula.auth_flow.create_client", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = MagicMock()
            result = await authenticate_and_create_client("user", token_storage)

        mock_create.assert_awaited_once()
        # Verify create_client received the token_data from authenticate
        call_args = mock_create.call_args[0][0]
        assert call_args["tokens"]["access_token"] == "fresh-tok"
        assert result is mock_create.return_value

    @pytest.mark.asyncio
    async def test_retries_with_force_login_on_authentication_error(self, token_storage):
        """create_client auth failure triggers forced re-auth and second create attempt."""
        cached_token_data = {
            "tokens": {"access_token": "cached-tok"},
            "cookies": {"PHPSESSID": "stale"},
        }
        fresh_token_data = {
            "tokens": {"access_token": "fresh-tok"},
            "cookies": {"PHPSESSID": "fresh"},
        }
        recovered_client = MagicMock()

        with (
            patch("aula.auth_flow.authenticate", new_callable=AsyncMock) as mock_authenticate,
            patch("aula.auth_flow.create_client", new_callable=AsyncMock) as mock_create,
        ):
            mock_authenticate.side_effect = [cached_token_data, fresh_token_data]
            mock_create.side_effect = [
                AulaAuthenticationError("HTTP 403", status_code=403),
                recovered_client,
            ]
            result = await authenticate_and_create_client("user", token_storage)

        assert mock_authenticate.await_count == 2
        assert mock_authenticate.await_args_list[0].args == (
            "user",
            token_storage,
            None,
            None,
            None,
        )
        assert "force_login" not in mock_authenticate.await_args_list[0].kwargs
        assert mock_authenticate.await_args_list[1].args == (
            "user",
            token_storage,
            None,
            None,
            None,
        )
        assert mock_authenticate.await_args_list[1].kwargs["force_login"] is True
        assert mock_create.await_count == 2
        assert mock_create.await_args_list[0].args[0] == cached_token_data
        assert mock_create.await_args_list[1].args[0] == fresh_token_data
        assert result is recovered_client

    @pytest.mark.asyncio
    async def test_passes_callbacks_through(self, token_storage, mock_auth_client):
        """Callbacks are forwarded to authenticate."""
        token_storage.load.return_value = None
        qr_cb = MagicMock()
        login_cb = MagicMock()

        with (
            patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client),
            patch("aula.auth_flow.create_client", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = MagicMock()
            await authenticate_and_create_client(
                "user",
                token_storage,
                on_qr_codes=qr_cb,
                on_login_required=login_cb,
            )

        login_cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_httpx_client_passed_to_mitid_auth(self, token_storage, mock_auth_client):
        """httpx_client is forwarded to MitIDAuthClient constructor."""
        fake_httpx = MagicMock()

        with (
            patch("aula.auth_flow.MitIDAuthClient", return_value=mock_auth_client) as MockMitID,
            patch("aula.auth_flow.create_client", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = MagicMock()
            await authenticate_and_create_client("user", token_storage, httpx_client=fake_httpx)

        MockMitID.assert_called_once_with(
            mitid_username="user",
            on_qr_codes=None,
            httpx_client=fake_httpx,
            on_identity_selected=None,
            auth_method="app",
            on_token_digits=None,
            on_password=None,
        )


# ---------------------------------------------------------------------------
# Client ownership (close behavior)
# ---------------------------------------------------------------------------


class TestClientOwnership:
    """Tests for ownership semantics when injecting httpx clients."""

    @pytest.mark.asyncio
    async def test_mitid_client_closes_own_client(self):
        """MitIDAuthClient closes its own httpx client."""
        from aula.auth.mitid_client import MitIDAuthClient

        with patch("aula.auth.mitid_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            client = MitIDAuthClient(mitid_username="user")
            await client.close()

        mock_instance.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mitid_client_does_not_close_injected_client(self):
        """MitIDAuthClient does NOT close an injected httpx client."""
        from aula.auth.mitid_client import MitIDAuthClient

        injected = AsyncMock()
        client = MitIDAuthClient(mitid_username="user", httpx_client=injected)
        await client.close()

        injected.aclose.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_httpx_http_client_closes_own_client(self):
        """HttpxHttpClient closes its own httpx client."""
        from aula.http_httpx import HttpxHttpClient

        with patch("aula.http_httpx.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            client = HttpxHttpClient()
            await client.close()

        mock_instance.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_httpx_http_client_does_not_close_injected_client(self):
        """HttpxHttpClient does NOT close an injected httpx client."""
        from aula.http_httpx import HttpxHttpClient

        injected = AsyncMock()
        client = HttpxHttpClient(httpx_client=injected)
        await client.close()

        injected.aclose.assert_not_awaited()
