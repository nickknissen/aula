"""Python client for Aula."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aula")
except PackageNotFoundError:
    __version__ = "0.1.0"

from .api_client import AulaApiClient
from .auth_flow import authenticate, authenticate_and_create_client, create_client
from .http import (
    AulaApiVersionError,
    AulaAuthenticationError,
    AulaConnectionError,
    AulaLoginRequiredError,
    AulaNotFoundError,
    AulaRateLimitError,
    AulaRejectedError,
    AulaResponseError,
    AulaServerError,
    DownloadTooLargeError,
    HttpClient,
    HttpRequestError,
    HttpResponse,
    ProviderAuthenticationError,
)
from .http_httpx import HttpxHttpClient
from .models import (
    ActivityType,
    Attachment,
    AttachmentDocument,
    AttachmentFile,
    AttachmentLink,
    AttachmentMedia,
    CalendarEvent,
    Child,
    DailyOverview,
    Message,
    MessageThread,
    PresenceState,
    Profile,
    WidgetConfiguration,
)
from .token_storage import FileTokenStorage, TokenStorage
from .utils.qr import TerminalQRDisplay
from .widgets import AulaWidgetsClient

__all__ = [
    "AulaApiClient",
    "AulaWidgetsClient",
    "authenticate",
    "authenticate_and_create_client",
    "create_client",
    "AulaApiVersionError",
    "AulaAuthenticationError",
    "AulaConnectionError",
    "AulaLoginRequiredError",
    "AulaNotFoundError",
    "AulaRateLimitError",
    "AulaRejectedError",
    "AulaResponseError",
    "AulaServerError",
    "DownloadTooLargeError",
    "FileTokenStorage",
    "HttpClient",
    "HttpRequestError",
    "HttpResponse",
    "HttpxHttpClient",
    "ProviderAuthenticationError",
    "TerminalQRDisplay",
    "TokenStorage",
    "Profile",
    "Child",
    "DailyOverview",
    "MessageThread",
    "Message",
    "CalendarEvent",
    "WidgetConfiguration",
    "ActivityType",
    "Attachment",
    "AttachmentDocument",
    "AttachmentFile",
    "AttachmentLink",
    "AttachmentMedia",
    "PresenceState",
    "__version__",
]
