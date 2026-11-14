"""httpx-based implementation of the HttpClient protocol."""

from typing import Any

import httpx

from .const import USER_AGENT
from .http import AulaConnectionError, DownloadTooLargeError, HttpResponse


def _connection_error(url: str, err: httpx.TransportError) -> AulaConnectionError:
    return AulaConnectionError(
        f"Could not reach {httpx.URL(url).host}: {str(err) or type(err).__name__}"
    )


async def _read_at_most(response: httpx.Response, max_bytes: int) -> bytes:
    too_large = DownloadTooLargeError(
        f"Download from {response.url.host} is larger than {max_bytes} bytes",
        max_bytes=max_bytes,
    )
    content_length = response.headers.get("Content-Length", "")
    if content_length.isdigit() and int(content_length) > max_bytes:
        raise too_large
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > max_bytes:
            raise too_large
    return bytes(body)


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
        try:
            response = await self._client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
            )
        except httpx.TransportError as err:
            raise _connection_error(url, err) from err
        try:
            data = response.json()
        except ValueError, UnicodeDecodeError:
            data = None
        return HttpResponse(
            status_code=response.status_code,
            data=data,
            headers=dict(response.headers),
        )

    async def download_bytes(self, url: str, *, max_bytes: int | None = None) -> bytes:
        try:
            async with self._client.stream(
                "GET", url, timeout=httpx.Timeout(30.0, read=120.0)
            ) as response:
                response.raise_for_status()
                if max_bytes is None:
                    return await response.aread()
                return await _read_at_most(response, max_bytes)
        except httpx.TransportError as err:
            raise _connection_error(url, err) from err

    def get_cookie(self, name: str) -> str | None:
        """Read a cookie from the underlying httpx session."""
        return self._client.cookies.get(name)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
