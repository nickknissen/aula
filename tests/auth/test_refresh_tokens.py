"""Refresh-token rotation and persistence through the real refresh path."""

import time
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from aula.auth.exceptions import NetworkError, OAuthError
from aula.auth.mitid_client import MitIDAuthClient
from aula.auth_flow import authenticate
from aula.const import OAUTH_TOKEN_PATH


@pytest.mark.asyncio
@pytest.mark.parametrize("rotated", [None, "rotated-refresh"])
async def test_direct_refresh_keeps_returned_and_client_credentials_consistent(rotated):
    payload = {"access_token": "new-access", "expires_in": 3600}
    if rotated is not None:
        payload["refresh_token"] = rotated
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as http:
        client = MitIDAuthClient("tester", httpx_client=http)
        tokens = await client.refresh_access_token("original-refresh")
        assert tokens["refresh_token"] == client.refresh_token == (rotated or "original-refresh")
        assert client.tokens == tokens
        assert client.access_token == "new-access"
        assert tokens["expires_at"] > time.time()


@pytest.mark.asyncio
@pytest.mark.parametrize("rotated", [None, "rotated-refresh"])
async def test_expired_cache_saves_reusable_refresh_token(rotated):
    storage = AsyncMock()
    storage.load.return_value = {
        "tokens": {"access_token": "expired", "refresh_token": "original-refresh", "expires_at": 1},
        "cookies": {"PHPSESSID": "session"},
    }
    payload = {"access_token": "new-access", "expires_in": 3600}
    if rotated is not None:
        payload["refresh_token"] = rotated
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as http:
        result = await authenticate("tester", storage, httpx_client=http)
    assert result["tokens"]["refresh_token"] == (rotated or "original-refresh")
    assert result["tokens"]["access_token"] == "new-access"
    assert result["tokens"]["expires_at"] > time.time()
    assert result["cookies"] == {"PHPSESSID": "session"}
    storage.save.assert_awaited_once_with(result)


def _token_server_down(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, text="Service Unavailable")


def _token_server_unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("timed out", request=request)


@pytest.mark.asyncio
@pytest.mark.parametrize("token_server", [_token_server_down, _token_server_unreachable])
async def test_expired_cache_does_not_start_mitid_login_while_token_server_is_down(token_server):
    storage = AsyncMock()
    storage.load.return_value = {
        "tokens": {"access_token": "expired", "refresh_token": "original-refresh", "expires_at": 1},
        "cookies": {},
    }
    requested_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return token_server(request)

    login_required = Mock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(NetworkError):
            await authenticate(
                "tester", storage, httpx_client=http, on_login_required=login_required
            )

    assert requested_paths == [OAUTH_TOKEN_PATH]
    login_required.assert_not_called()
    storage.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_rejection_does_not_replace_client_credentials():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(400, json={}))
    ) as http:
        client = MitIDAuthClient("tester", httpx_client=http)
        original = {"access_token": "expired", "refresh_token": "original-refresh"}
        client.tokens = original.copy()
        with pytest.raises(OAuthError, match="Token refresh failed"):
            await client.refresh_access_token("original-refresh")
        assert client.tokens == original
