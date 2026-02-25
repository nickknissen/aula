"""Transport-agnostic HTTP client protocol and response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class HttpRequestError(Exception):
    """Raised when an HTTP request fails with a non-2xx status code."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class AulaAuthenticationError(HttpRequestError):
    """Raised when authentication fails (401 Unauthorized, 403 Forbidden).

    This error indicates that the current credentials are invalid or have expired.
    Home Assistant integrations should trigger a reauthentication flow when this occurs.
    """

    pass


class AulaRateLimitError(HttpRequestError):
    """Raised when the API rate limit is exceeded (429 Too Many Requests).

    This error indicates temporary unavailability due to rate limiting.
    Callers should implement exponential backoff before retrying.
    """

    pass


class AulaServerError(HttpRequestError):
    """Raised when the server returns an error (5xx status codes).

    This error indicates a temporary server-side problem.
    Entities should be marked as unavailable, and retries should be attempted.
    """

    pass


class AulaNotFoundError(HttpRequestError):
    """Raised when a resource is not found (404 Not Found).

    This error indicates the requested resource does not exist.
    Retries are not helpful; the caller should skip this resource.
    """

    pass


class AulaConnectionError(HttpRequestError):
    """Raised when a network connection error occurs (timeout, network unreachable, etc).

    This error indicates a transient network problem.
    Entities should be marked as unavailable, and retries should be attempted with backoff.
    """

    def __init__(self, message: str, status_code: int = 0) -> None:
        """Initialize connection error with optional status code (0 for network errors)."""
        super().__init__(message, status_code)


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
        """Raise appropriate exception if the response status is 4xx or 5xx.

        Raises:
            AulaAuthenticationError: For 401 or 403 status codes
            AulaRateLimitError: For 429 status code
            AulaServerError: For 5xx status codes
            AulaNotFoundError: For 404 status code
            HttpRequestError: For other 4xx status codes
        """
        if self.status_code >= 400:
            if self.status_code == 401 or self.status_code == 403:
                raise AulaAuthenticationError(
                    f"HTTP {self.status_code}",
                    status_code=self.status_code,
                )
            elif self.status_code == 429:
                raise AulaRateLimitError(
                    f"HTTP {self.status_code}",
                    status_code=self.status_code,
                )
            elif self.status_code == 404:
                raise AulaNotFoundError(
                    f"HTTP {self.status_code}",
                    status_code=self.status_code,
                )
            elif self.status_code >= 500:
                raise AulaServerError(
                    f"HTTP {self.status_code}",
                    status_code=self.status_code,
                )
            else:
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
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> HttpResponse: ...

    async def download_bytes(self, url: str) -> bytes: ...

    def get_cookie(self, name: str) -> str | None:
        """Read a cookie value by name from the underlying session.

        Returns None by default. Implementations backed by a cookie-aware
        HTTP client (e.g. httpx) should override this.
        """
        return None

    async def close(self) -> None: ...
