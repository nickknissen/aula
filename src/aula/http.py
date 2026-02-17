"""Transport-agnostic HTTP client protocol and response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class HttpRequestError(Exception):
    """Raised when an HTTP request fails with a non-2xx status code."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class HttpResponse:
    """Transport-agnostic HTTP response with pre-parsed JSON data.

    Implementations should parse JSON eagerly so that .json() is always sync.
    """

    status_code: int
    data: Any = None
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        """Return pre-parsed JSON data."""
        return self.data

    def raise_for_status(self) -> None:
        """Raise HttpRequestError if the response status is 4xx or 5xx."""
        if self.status_code >= 400:
            raise HttpRequestError(
                f"HTTP {self.status_code}",
                status_code=self.status_code,
            )


@runtime_checkable
class HttpClient(Protocol):
    """Protocol for HTTP transport backends.

    Implementations must parse JSON eagerly in request() and return it
    via HttpResponse.data so that callers can use .json() synchronously.
    """

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
        json: Any | None = None,
    ) -> HttpResponse: ...

    def get_cookie(self, name: str) -> str | None: ...

    async def close(self) -> None: ...
