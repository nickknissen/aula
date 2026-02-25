"""Python client for Aula."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aula")
except PackageNotFoundError:
    __version__ = "0.1.0"

from .api_client import AulaApiClient
from .auth_flow import create_client
from .http import (
    AulaAuthenticationError,
    AulaConnectionError,
    AulaNotFoundError,
    AulaRateLimitError,
    AulaServerError,
    HttpClient,
    HttpRequestError,
    HttpResponse,
)
from .http_httpx import HttpxHttpClient
from .models import (
    CalendarEvent,
    Child,
    DailyOverview,
    Message,
    MessageThread,
    Profile,
)
from .token_storage import FileTokenStorage, TokenStorage

__all__ = [
    "AulaApiClient",
    "create_client",
    "AulaAuthenticationError",
    "AulaConnectionError",
    "AulaNotFoundError",
    "AulaRateLimitError",
    "AulaServerError",
    "FileTokenStorage",
    "HttpClient",
    "HttpRequestError",
    "HttpResponse",
    "HttpxHttpClient",
    "TokenStorage",
    "Profile",
    "Child",
    "DailyOverview",
    "MessageThread",
    "Message",
    "CalendarEvent",
    "__version__",
]
