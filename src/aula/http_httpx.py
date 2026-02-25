"""httpx-based implementation of the HttpClient protocol."""

from __future__ import annotations

from typing import Any

import httpx

from .const import USER_AGENT
from .http import HttpResponse


class HttpxHttpClient:
    """HttpClient implementation backed by httpx.AsyncClient.

    Args:
        cookies: Optional cookies to set on a new internal client.
        httpx_client: Optional pre-configured ``httpx.AsyncClient``.  When
            provided, the caller retains ownership and must close it.
            The *cookies* parameter is ignored when *httpx_client* is given.
    """

    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        httpx_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = httpx_client is None
        self._client = httpx_client or httpx.AsyncClient(
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
        params: dict[str, Any] | None = None,
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
        """Read a cookie from the underlying httpx session."""
        return self._client.cookies.get(name)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
