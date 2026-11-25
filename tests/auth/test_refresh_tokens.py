"""Refresh-token rotation and persistence through the real refresh path."""

import time
from unittest.mock import AsyncMock

import httpx
import pytest

from aula.auth.exceptions import OAuthError
from aula.auth.mitid_client import MitIDAuthClient
from aula.auth_flow import authenticate


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
