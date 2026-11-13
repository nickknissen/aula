import logging
import time
from typing import Any

from ..http import HttpClient, ProviderAuthenticationError
from ..utils.diagnostics import compact_payload_for_log, credential_logger

_LOGGER = credential_logger(__name__)


class ProviderTransport:
    """Sends requests to widget providers, outside the Aula session.

    It never retries and never refreshes the Aula session (docs/adr/0001). The
    caller mints the widget token and puts it in whichever header its provider
    reads.
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    async def send(
        self,
        widget_id: str,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: object | None = None,
    ) -> Any:
        """Send one request and return its JSON body, or ``None`` when it has none.

        Raises :class:`ProviderAuthenticationError` on 401 and 403, and the
        usual :class:`HttpRequestError` subclasses on any other 4xx or 5xx.
        """
        start = time.monotonic()
        resp = await self._http.request(method, url, headers=headers, params=params, json=json)
        _LOGGER.debug(
            "%s %s widget=%s -> %d (%.2fs)",
            method.upper(),
            url.split("?")[0],
            widget_id,
            resp.status_code,
            time.monotonic() - start,
        )
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Response widget=%s: %s", widget_id, compact_payload_for_log(resp.json()))

        if resp.status_code in (401, 403):
            raise ProviderAuthenticationError(
                f"Provider refused widget {widget_id} (HTTP {resp.status_code})",
                resp.status_code,
                widget_id=widget_id,
            )
        resp.raise_for_status()
        return resp.json()
