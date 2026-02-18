"""httpx-based implementation of the HttpClient protocol."""

from __future__ import annotations

from typing import Any

import httpx

from .const import USER_AGENT
from .http import HttpResponse


class HttpxHttpClient:
    """HttpClient implementation backed by httpx.AsyncClient."""

    def __init__(self, cookies: dict[str, str] | None = None) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            cookies=cookies,
            timeout=httpx.Timeout(30.0, read=60.0),
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
        json: Any | None = None,
    ) -> HttpResponse:
        response = await self._client.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json,
        )
        try:
            data = response.json()
        except (ValueError, UnicodeDecodeError):
            data = None
        return HttpResponse(
            status_code=response.status_code,
            data=data,
            headers=dict(response.headers),
        )

    async def download_bytes(self, url: str) -> bytes:
        response = await self._client.get(url, timeout=httpx.Timeout(30.0, read=120.0))
        response.raise_for_status()
        return response.content

    def get_cookie(self, name: str) -> str | None:
        return self._client.cookies.get(name)

    async def close(self) -> None:
        await self._client.aclose()
