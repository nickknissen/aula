import asyncio
import inspect
import logging
import re
import time
import warnings
from collections.abc import Awaitable, Callable, Iterable, Iterator, Sized
from contextvars import ContextVar
from datetime import date, datetime, timedelta
from types import TracebackType
from typing import Any, Self
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from .const import (
    API_URL,
    API_VERSION,
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
)
from .http import (
    AulaApiVersionError,
    AulaAuthenticationError,
    AulaConnectionError,
    AulaInvalidTokenError,
    AulaLoginRequiredError,
    AulaRateLimitError,
    AulaRefreshTokenConflictError,
    AulaRejectedError,
    AulaResponseError,
    AulaServerError,
    AulaSessionExpiredError,
    AulaStepUpRequiredError,
    AulaUserDeactivatedError,
    HttpClient,
    HttpRequestError,
    HttpResponse,
)
from .models import (
    ActivityType,
    Appointment,
    AutoReply,
    CalendarEvent,
    Child,
    ChildPickupResponsibles,
    ChildPresenceState,
    Comment,
    CommonFile,
    ConsentResponse,
    DailyOverview,
    Group,
    GroupMember,
    LibraryStatus,
    MeebookStudentPlan,
    MeetingBooking,
    Message,
    MessageFolder,
    MessageThread,
    MomoUserCourses,
    MUTask,
    MUWeeklyPerson,
    Notification,
    NotificationSetting,
    Post,
    PresenceConfiguration,
    PresenceRegistration,
    PresenceRegistrationDetail,
    PresenceState,
    PresenceWeekOverview,
    PresenceWeekTemplate,
    Profile,
    ProfileMasterData,
    SecureDocument,
    VacationRegistration,
    WidgetConfiguration,
    merge_duplicate_lessons,
)
from .models.meeting_booking import MEETING_TYPES, meeting_bookings, replace_booked_meetings
from .models.pagination import PaginationResult
from .utils.dates import aula_today
from .utils.diagnostics import compact_payload_for_log, credential_logger
from .utils.mapping import get_in
from .utils.pagination import PaginationState
from .widgets import AulaWidgetsClient

# Logger
_LOGGER = credential_logger(__name__)

# Safety limit for paginated requests to prevent infinite loops
MAX_PAGES = 100

_API_VERSION_PATTERN = re.compile(rf"{re.escape(API_URL)}(\d+)")

_RECORD_ERRORS = (KeyError, TypeError, ValueError, AttributeError)


def _describe_body(response: HttpResponse) -> str:
    """Render a response for the debug log without failing on a body that is not JSON."""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if payload is not None:
        return compact_payload_for_log(payload)
    headers = {name.lower(): value for name, value in response.headers.items()}
    return (
        f"<non-JSON body content-type={headers.get('content-type', 'unknown')} "
        f"length={headers.get('content-length', 'unknown')}>"
    )


def _response_body(response: HttpResponse) -> dict[str, Any]:
    """Return the JSON object Aula answered with, or raise ``AulaResponseError``."""
    try:
        body = response.json()
    except ValueError as e:
        raise AulaResponseError(
            "Aula answered with a body that is not JSON", response.status_code
        ) from e
    if not isinstance(body, dict):
        raise AulaResponseError(
            f"Expected a JSON object from Aula, got {type(body).__name__}",
            response.status_code,
        )
    return body


def _as_object(value: Any, where: str, status_code: int) -> dict[str, Any]:
    """Return ``value`` as an object, ``{}`` when null or ``[]``, or raise ``AulaResponseError``."""
    if value is None or value == []:
        return {}
    if not isinstance(value, dict):
        raise AulaResponseError(
            f"Expected a JSON object in {where}, got {type(value).__name__}", status_code
        )
    return value


def _as_list(value: Any, where: str, status_code: int) -> list[Any]:
    """Return ``value`` as a list, ``[]`` when it is null, or raise ``AulaResponseError``."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise AulaResponseError(
            f"Expected a JSON list in {where}, got {type(value).__name__}", status_code
        )
    return value


def _response_data_object(response: HttpResponse) -> dict[str, Any]:
    """Return the object in ``data``, ``{}`` when empty, or raise ``AulaResponseError``."""
    return _as_object(_response_body(response).get("data"), "data", response.status_code)


def _response_data_list(response: HttpResponse) -> list[Any]:
    """Return the list in ``data``, ``[]`` when empty, or raise ``AulaResponseError``."""
    return _as_list(_response_body(response).get("data"), "data", response.status_code)


def _parse_object[T](
    parse: Callable[[dict[str, Any]], T], data: dict[str, Any], what: str, status_code: int
) -> T:
    """Parse one object Aula answered with, or raise ``AulaResponseError``."""
    try:
        return parse(data)
    except _RECORD_ERRORS as e:
        raise AulaResponseError(f"Could not parse the {what} from Aula", status_code) from e


class _SkippedRecords:
    """Logs and counts the records a parse loop skipped, so a loop that kept none can raise."""

    def __init__(self, record_type: str) -> None:
        self.record_type = record_type
        self.count = 0
        self.last_error: Exception | None = None

    def objects(self, items: Iterable[Any]) -> Iterator[Any]:
        """Yield the items that are objects and skip the others as failed records."""
        for item in items:
            if isinstance(item, dict):
                yield item
            else:
                self.add(TypeError(f"expected an object, got {type(item).__name__}"), item)

    def add(self, error: Exception, record: Any = None) -> None:
        """Count a record that failed and warn with its error type and keys; values go to DEBUG."""
        self.count += 1
        self.last_error = error
        keys = sorted(str(key) for key in record) if isinstance(record, dict) else []
        _LOGGER.warning(
            "Skipping %s: %s (keys: %s)",
            self.record_type,
            type(error).__name__,
            ", ".join(keys) or "none",
        )
        _LOGGER.debug("Skipped %s payload: %s", self.record_type, compact_payload_for_log(record))

    def raise_if_none_parsed(self, parsed: Sized, status_code: int) -> None:
        """Raise ``AulaResponseError`` when records were skipped and none parsed."""
        if self.count and not parsed:
            raise AulaResponseError(
                f"Could not parse any of the {self.count} {self.record_type} records from Aula",
                status_code,
            ) from self.last_error


def _api_version_of(url: str) -> int | None:
    match = _API_VERSION_PATTERN.match(url)
    return int(match.group(1)) if match else None


def _extract_api_method(url: str, params: dict[str, Any] | None) -> str | None:
    method = None
    if params and isinstance(params.get("method"), str):
        method = params["method"]
    if method:
        return method

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    raw_method = query.get("method", [None])[0]
    if isinstance(raw_method, str) and raw_method:
        return raw_method
    return None


def _teacher_names(lesson: dict[str, Any], role: str) -> list[str]:
    """Return every named participant on ``lesson`` holding ``role``.

    Aula usually splits a co-taught lesson across one row per adult, which
    ``merge_duplicate_lessons`` folds back together, but a single row has also
    been seen carrying several participants in the same role. Reading all of
    them here means both shapes end up with a complete teacher list.
    """
    participants = lesson.get("participants", [])
    if not isinstance(participants, list):
        return []
    names = [
        p.get("teacherName")
        for p in participants
        if isinstance(p, dict) and p.get("participantRole") == role
    ]
    return list(dict.fromkeys(name for name in names if name))


def _profile_ids(value: object) -> list[int]:
    """Return the institution profile IDs in a ``belongsToProfiles`` value."""
    if not isinstance(value, list):
        return []
    return [p for p in value if type(p) is int]


VACATION_COMMENT_MAX_LENGTH = 250


def validate_vacation(start_date: date, end_date: date, comment: str, *, today: date) -> None:
    """Raise ValueError for an absence the guardian portal would not let you create.

    These are the portal's own form rules; the limits the server enforces are untested.
    """
    if start_date < today:
        raise ValueError(f"the absence cannot start in the past ({start_date} is before {today})")
    if end_date < start_date:
        raise ValueError(f"end date {end_date} is before start date {start_date}")
    latest_end = _one_year_after(start_date)
    if end_date > latest_end:
        raise ValueError(
            f"end date {end_date} is more than a year after start date {start_date} "
            f"(latest {latest_end})"
        )
    if len(comment) > VACATION_COMMENT_MAX_LENGTH:
        raise ValueError(
            f"comment is {len(comment)} characters; Aula allows at most "
            f"{VACATION_COMMENT_MAX_LENGTH}"
        )


def _one_year_after(day: date) -> date:
    if (day.month, day.day) == (2, 29):
        return date(day.year + 1, 2, 28)
    return day.replace(year=day.year + 1)


# Message types Aula's web client accepts as the target of a read marker.
_MARKABLE_MESSAGE_TYPES = ("Message", "MessageEdited", "MessageDeleted", "AutoReply")
# Upper bound on pages of 20 read while looking for a message in one thread.
_MAX_THREAD_PAGES = 50


class ThreadScanLimitError(Exception):
    """Raised when a thread's first pages hold no message, but Aula reports more pages."""


class AulaApiClient:
    """Async client for Aula API endpoints.

    Transport-agnostic: accepts any HttpClient implementation (httpx, aiohttp, etc.).
    Authentication uses ``access_token`` as a query parameter during ``init()``
    to establish a server-side session, then relies on session cookies for all
    subsequent API requests.

    ``session_cookies`` are the cookies saved at login. When Aula refuses a call
    (status code 10) after an automatic token refresh, the client starts a new
    session from them once and replays the call.
    """

    _CODE_AUTHORIZATION_DENIED = 10

    # API response sub-codes from the Aula backend envelope (status.subCode).
    # Values match WebResponseStatusSubCodeConstants in the decompiled
    # AulaNative.dll, where SessionExpiredErrorHandler checks sub-code 23.
    _SUBCODE_USER_DEACTIVATED = 7
    _SUBCODE_STEP_UP_REQUIRED = 8
    _SUBCODE_INVALID_TOKEN = 9
    _SUBCODE_SESSION_EXPIRED = 23

    def __init__(
        self,
        http_client: HttpClient,
        access_token: str | None = None,
        csrf_token: str | None = None,
        on_token_refresh: Callable[[], Awaitable[str | None]] | None = None,
        session_cookies: dict[str, str] | None = None,
    ) -> None:
        self._client = http_client
        self._access_token = access_token
        self._csrf_token = csrf_token
        self._on_token_refresh = on_token_refresh
        self._session_cookies = dict(session_cookies) if session_cookies is not None else None
        self._new_session_access_token: str | None = None
        self._auth_refresh_lock = asyncio.Lock()
        self._auth_generation = 0
        self._auth_refresh_context: ContextVar[bool] = ContextVar(
            "aula_auth_refresh_context", default=False
        )
        self.api_url = f"{API_URL}{API_VERSION}"
        self._api_version_lock = asyncio.Lock()
        self.widgets: AulaWidgetsClient = AulaWidgetsClient(self)

    @property
    def http_client(self) -> HttpClient:
        """The HttpClient this client sends through. Widget providers share it."""
        return self._client

    async def init(self) -> None:
        """Discover the current API version and establish guardian role.

        Uses ``access_token`` as a query parameter for these initial requests
        to establish a server-side session. After init completes, the access
        token is cleared and all subsequent requests rely on session cookies.
        """
        await self._set_correct_api_version()

        # Establish guardian role in the session (required for child-specific endpoints).
        # deviceId mirrors the mobile app's context init (discovered via aulalibre).
        await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=profiles.getProfileContext&portalrole=guardian&deviceId=aula-cli",
        )

        # Session is now established via cookies; access_token no longer needed.
        self._access_token = None

        # Capture CSRF token set by the server during the session setup.
        # The Csrfp-Token cookie is not part of the stored auth credentials;
        # it's set by Aula via Set-Cookie during these initial GET requests.
        if self._csrf_token is None:
            self._csrf_token = self._client.get_cookie(CSRF_TOKEN_COOKIE)

    async def _set_correct_api_version(self) -> None:
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=profiles.getProfilesByLogin",
        )
        resp.raise_for_status()

    @staticmethod
    def _extract_sub_code(response: HttpResponse) -> int | None:
        """Extract the sub-code from the Aula API response envelope.

        The Aula backend wraps responses in ``{"status": {"code": N, "subCode": M}, "data": ...}``.
        Sub-codes carry auth/session state that HTTP status codes alone don't convey.
        """
        data = response.json()
        if not isinstance(data, dict):
            return None
        status = data.get("status")
        if not isinstance(status, dict):
            return None
        sub_code = status.get("subCode")
        return int(sub_code) if sub_code is not None else None

    @staticmethod
    def _extract_status_code(response: HttpResponse) -> object:
        """Return ``status.code`` from the Aula API response envelope, if any."""
        data = response.json()
        status = data.get("status") if isinstance(data, dict) else None
        return status.get("code") if isinstance(status, dict) else None

    def _raise_for_sub_code(self, sub_code: int, api_method: str | None) -> None:
        """Raise a specific error for known Aula API sub-codes."""
        method_info = f" (method={api_method})" if api_method else ""
        if sub_code == self._SUBCODE_USER_DEACTIVATED:
            raise AulaUserDeactivatedError(
                f"User account is deactivated{method_info}", status_code=403
            )
        if sub_code == self._SUBCODE_STEP_UP_REQUIRED:
            raise AulaStepUpRequiredError(
                f"Elevated authentication (MitID Level 3) required{method_info}",
                status_code=403,
            )
        if sub_code == self._SUBCODE_INVALID_TOKEN:
            raise AulaInvalidTokenError(f"Invalid access token{method_info}", status_code=401)
        if sub_code == self._SUBCODE_SESSION_EXPIRED:
            raise AulaSessionExpiredError(f"Session expired{method_info}", status_code=401)

    def _raise_for_auth_failure(
        self, response: HttpResponse, url: str, params: dict[str, Any] | None
    ) -> None:
        """Raise the authentication error a response carries in its sub-code or status."""
        sub_code = self._extract_sub_code(response)
        if sub_code is not None:
            self._raise_for_sub_code(sub_code, _extract_api_method(url, params))
        response.raise_for_status()

    async def _request_with_version_retry(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: object | None = None,
    ) -> HttpResponse:
        """Make an HTTP request with automatic API version bump on 410 Gone.

        During ``init()``, ``access_token`` is appended as a query parameter
        to establish the server-side session. After init clears the token,
        requests rely on session cookies only.

        For POST requests to the Aula API, the ``csrfp-token`` header is
        automatically included (matching the browser's behavior where every
        POST carries this header).

        On HTTP 401 or API sub-code 9 (InvalidToken) or 23 (SessionExpired),
        attempts a single token refresh via the ``on_token_refresh`` callback
        (if provided), re-inits the session, and retries the request. Widget
        provider URLs never trigger a refresh. When the refresh fails because
        a server is down or unreachable, that ``AulaServerError`` or
        ``AulaConnectionError`` is raised instead of returning the 401. When the
        refresh callback raises ``AulaLoginRequiredError``, that error is raised
        with the original authentication error as its cause.
        ``AulaRefreshTokenConflictError`` from the callback is raised unchanged.

        When Aula answers status code 10 after a refresh, starts a new session
        once (see ``_start_new_session``) and replays the request. Once a call
        on the refreshed session succeeds, code 10 is Aula's real answer and
        is raised at once.
        """
        is_aula_call = url.startswith(API_URL)
        observed_generation = self._auth_generation
        response = await self._do_request(method, url, headers=headers, params=params, json=json)

        # Check for auth failures that can be recovered via token refresh.
        # Only attempt once to avoid infinite loops.
        if is_aula_call and not self._auth_refresh_context.get() and self._on_token_refresh:
            needs_retry = response.status_code == 401
            if not needs_retry:
                sub_code = self._extract_sub_code(response)
                needs_retry = sub_code in (
                    self._SUBCODE_INVALID_TOKEN,
                    self._SUBCODE_SESSION_EXPIRED,
                )

            if needs_retry:
                _LOGGER.warning(
                    "Auth failure (HTTP %d), attempting token refresh and retry",
                    response.status_code,
                )
                try:
                    refreshed = await self._refresh_authentication(observed_generation)
                except AulaLoginRequiredError as rejected:
                    try:
                        self._raise_for_auth_failure(response, url, params)
                    except AulaAuthenticationError as original:
                        raise AulaLoginRequiredError(
                            str(rejected), original.status_code
                        ) from original
                    raise
                if refreshed:
                    observed_generation = self._auth_generation
                    response = await self._do_request(
                        method, url, headers=headers, params=params, json=json
                    )

        status_code = self._extract_status_code(response) if is_aula_call else None
        if (
            status_code == self._CODE_AUTHORIZATION_DENIED
            and not self._auth_refresh_context.get()
            and await self._start_new_session(observed_generation)
        ):
            response = await self._do_request(
                method, url, headers=headers, params=params, json=json
            )
        elif status_code == 0 and observed_generation == self._auth_generation:
            self._new_session_access_token = None

        # After retry (or no retry), check for sub-code errors on the final response.
        sub_code = self._extract_sub_code(response) if is_aula_call else None
        if sub_code is not None:
            api_method = _extract_api_method(url, params)
            self._raise_for_sub_code(sub_code, api_method)

        if is_aula_call:
            body = response.json()
            status = body.get("status") if isinstance(body, dict) else None
            if isinstance(status, dict) and status.get("code") is not None:
                code = status["code"]
                if code != 0:
                    api_method = _extract_api_method(url, params)
                    detail = f"status code {code}"
                    if sub_code is not None:
                        detail += f", sub-code {sub_code}"
                    detail += f", HTTP {response.status_code}"
                    raise AulaRejectedError(
                        f"Aula rejected {api_method or 'unknown method'} ({detail})",
                        response.status_code,
                        code=code,
                        sub_code=sub_code,
                        api_method=api_method,
                    )

        return response

    async def _refresh_authentication(
        self,
        observed_generation: int | None = None,
        *,
        force: bool = False,
    ) -> bool:
        """Refresh and reinitialize authentication once for concurrent callers.

        A caller that waited for another request's successful refresh can
        replay immediately when its observed generation is stale. ``force``
        is reserved for providers that report token expiry in a successful
        HTTP response rather than through Aula's authentication status.
        """
        if self._on_token_refresh is None:
            return False

        async with self._auth_refresh_lock:
            if (
                not force
                and observed_generation is not None
                and observed_generation != self._auth_generation
            ):
                return True

            previous_access_token = self._access_token
            refresh_context_token = self._auth_refresh_context.set(True)
            try:
                new_token = await self._on_token_refresh()
                if not new_token:
                    return False
                self._access_token = new_token
                await self.init()
                self._auth_generation += 1
                self._new_session_access_token = new_token
                return True
            except (
                AulaServerError,
                AulaRateLimitError,
                AulaConnectionError,
                AulaLoginRequiredError,
                AulaRefreshTokenConflictError,
            ):
                self._access_token = previous_access_token
                raise
            except Exception as e:
                self._access_token = previous_access_token
                _LOGGER.warning("Token refresh failed: %s", e)
                return False
            finally:
                self._auth_refresh_context.reset(refresh_context_token)

    async def _start_new_session(self, observed_generation: int) -> bool:
        """Start one new session from the login cookies and return whether to replay."""
        async with self._auth_refresh_lock:
            if observed_generation != self._auth_generation:
                return True

            access_token = self._new_session_access_token
            reset_cookies = getattr(self._client, "reset_cookies", None)
            if access_token is None or self._session_cookies is None or not callable(reset_cookies):
                return False

            _LOGGER.warning("Aula refused the refreshed session; starting a new session")
            self._new_session_access_token = None
            reset_cookies(self._session_cookies)
            self._csrf_token = self._session_cookies.get(CSRF_TOKEN_COOKIE)
            self._access_token = access_token
            refresh_context_token = self._auth_refresh_context.set(True)
            try:
                await self.init()
            finally:
                self._access_token = None
                self._auth_refresh_context.reset(refresh_context_token)
            self._auth_generation += 1
            return True

    async def _do_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: object | None = None,
    ) -> HttpResponse:
        """Execute an HTTP request with version retry on 410 Gone.

        This is the inner request loop handling access token injection,
        CSRF headers, and API version bumps.
        """
        if self._access_token and url.startswith(API_URL):
            if params is not None:
                params = {**params, "access_token": self._access_token}
            else:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}access_token={self._access_token}"

        # Auto-add csrfp-token header for POST requests to Aula API.
        # The browser sends this header on every POST; centralising it here
        # ensures new endpoints get it automatically.
        if method.lower() == "post" and url.startswith(API_URL):
            get_cookie = getattr(self._client, "get_cookie", None)
            if callable(get_cookie) and not inspect.iscoroutinefunction(get_cookie):
                csrf_from_cookie = get_cookie(CSRF_TOKEN_COOKIE)
                if isinstance(csrf_from_cookie, str) and csrf_from_cookie:
                    self._csrf_token = csrf_from_cookie

            if self._csrf_token:
                headers = dict(headers) if headers else {}
                headers.setdefault(CSRF_TOKEN_HEADER, self._csrf_token)
                headers.setdefault("content-type", "application/json")

        max_retries = 5
        for _attempt in range(max_retries):
            api_method = _extract_api_method(url, params)
            start = time.monotonic()
            response = await self._client.request(
                method, url, headers=headers, params=params, json=json
            )
            elapsed = time.monotonic() - start

            _LOGGER.debug(
                "%s %s method=%s -> %d (%.2fs)",
                method.upper(),
                url.split("?")[0],
                api_method or "unknown",
                response.status_code,
                elapsed,
            )

            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "Response method=%s: %s", api_method or "unknown", _describe_body(response)
                )

            failed_version = _api_version_of(url)
            if response.status_code == 410 and failed_version is not None:
                next_version = await self._move_past_api_version(failed_version)
                url = url.replace(f"{API_URL}{failed_version}", f"{API_URL}{next_version}", 1)
                continue

            return response

        raise AulaApiVersionError(
            f"Failed to find working API version after {max_retries} attempts"
        )

    async def _move_past_api_version(self, failed_version: int) -> int:
        """Bump ``api_url`` past a version that answered 410 and return the version to retry."""
        async with self._api_version_lock:
            current_version = _api_version_of(self.api_url)
            if current_version is None or failed_version >= current_version:
                new_version = failed_version + 1
                _LOGGER.warning(
                    "API version v%d is deprecated (410 Gone), automatically switching to v%d",
                    failed_version,
                    new_version,
                )
                self.api_url = f"{API_URL}{new_version}"
                return new_version
            return current_version

    async def get_profile(self) -> Profile:
        """Fetch the authenticated user's profile with children.

        Raises:
            HttpRequestError: If the API returns a 4xx/5xx error.
            ValueError: If no profile data is found.
            AulaResponseError: If the answer is not in the expected shape.
        """
        resp = await self._request_with_version_retry(
            "get", f"{self.api_url}?method=profiles.getProfilesByLogin"
        )
        resp.raise_for_status()
        raw_data_list = _as_list(
            _response_data_object(resp).get("profiles"), "data.profiles", resp.status_code
        )

        if not raw_data_list:
            raise ValueError("No profile data found in API response")
        if not isinstance(raw_data_list[0], dict):
            raise AulaResponseError(
                f"Expected a profile object, got {type(raw_data_list[0]).__name__}",
                resp.status_code,
            )

        profile_dict = raw_data_list[0]

        children = []
        skipped = _SkippedRecords("child")
        raw_children = _as_list(profile_dict.get("children"), "children", resp.status_code)
        for child_dict in skipped.objects(raw_children):
            try:
                children.append(Child.from_dict(child_dict))
            except _RECORD_ERRORS as e:
                skipped.add(e, child_dict)
        skipped.raise_if_none_parsed(children, resp.status_code)

        children.extend(await self._extended_access_children({child.id for child in children}))

        raw_institution_profiles = _as_list(
            profile_dict.get("institutionProfiles"), "institutionProfiles", resp.status_code
        )
        institution_profile_ids = [
            ip["id"] for ip in raw_institution_profiles if isinstance(ip, dict) and "id" in ip
        ]
        institution_profile_ids.extend([x.id for x in children])

        try:
            profile = Profile(
                _raw=profile_dict,
                profile_id=int(profile_dict.get("profileId")),
                display_name=str(profile_dict.get("displayName", "N/A")),
                children=children,
                institution_profile_ids=institution_profile_ids,
            )
        except (TypeError, ValueError) as e:
            raise AulaResponseError("Failed to parse main profile data", resp.status_code) from e

        return profile

    async def _extended_access_children(self, known_ids: set[int]) -> list[Child]:
        """Children the guardian has extended access to ("udvidet adgang", e.g. a bonus parent).

        Aula only lists them in ``getProfileContext``, not in ``getProfilesByLogin``.
        """
        try:
            context = await self.get_profile_context()
        except HttpRequestError as e:
            _LOGGER.warning("Could not fetch extended-access children: %s", e)
            return []

        children = []
        skipped = _SkippedRecords("extended-access child")
        for institution in get_in(context, "data.institutions", default=None) or []:
            if not isinstance(institution, dict):
                continue
            for child_dict in skipped.objects(institution.get("children") or []):
                if child_dict.get("id") in known_ids:
                    continue
                child_dict = {
                    **child_dict,
                    "institutionProfile": {
                        "institutionName": institution.get("name", ""),
                        "institutionCode": child_dict.get("institutionCode"),
                    },
                }
                try:
                    child = Child.from_dict(child_dict)
                except _RECORD_ERRORS as e:
                    skipped.add(e, child_dict)
                    continue
                known_ids.add(child.id)
                children.append(child)
        return children

    async def is_logged_in(self) -> bool:
        """Check if session is still authenticated."""
        try:
            await self.get_profile()
        except (HttpRequestError, ValueError) as e:
            _LOGGER.debug("is_logged_in check failed: %s", e)
            return False
        return True

    async def get_profile_context(self) -> dict[str, Any]:
        """Fetch the profile context for the current guardian session."""
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=profiles.getProfileContext&portalrole=guardian",
        )
        resp.raise_for_status()
        return _response_body(resp)

    async def get_widgets(self) -> list[WidgetConfiguration]:
        """Return the widget configurations available for the current user.

        Parses ``pageConfiguration.widgetConfigurations`` from the profile context response.
        Only widgets with ``aggregatedDisplayMode == "Shown"`` are included.
        """
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=profiles.getProfileContext&portalrole=guardian",
        )
        resp.raise_for_status()
        widget_configs = _as_list(
            get_in(_response_body(resp), "data.pageConfiguration.widgetConfigurations"),
            "data.pageConfiguration.widgetConfigurations",
            resp.status_code,
        )
        widgets = []
        skipped = _SkippedRecords("widget configuration")
        for item in skipped.objects(widget_configs):
            try:
                widgets.append(WidgetConfiguration.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(widgets, resp.status_code)
        return [w for w in widgets if w.aggregated_display_mode == "Shown"]

    async def get_daily_overview(self, child_id: int) -> DailyOverview | None:
        """Fetches the daily overview for a specific child.

        Returns None if no data is available for the child.

        Raises:
            HttpRequestError: If the API returns a 4xx/5xx error.
            AulaResponseError: If the answer is not a list of daily overviews.
        """
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=presence.getDailyOverview&childIds[]={child_id}",
        )
        resp.raise_for_status()
        data = _response_data_list(resp)
        if not data:
            _LOGGER.debug("No daily overview data for child %d", child_id)
            return None
        if not isinstance(data[0], dict):
            raise AulaResponseError(
                f"Expected a daily overview object, got {type(data[0]).__name__}",
                resp.status_code,
            )
        return _parse_object(
            DailyOverview.from_dict,
            data[0],
            f"daily overview for child {child_id}",
            resp.status_code,
        )

    async def get_presence_templates(
        self,
        institution_profile_ids: list[int],
        from_date: date,
        to_date: date,
    ) -> list[PresenceWeekTemplate]:
        """Fetch presence week templates for the given institution profile IDs and date range.

        Note: The parameter name 'filterInstitutionProfileIds[]' should be verified against
        actual API responses. Different Aula endpoints use different patterns (e.g.,
        institutionProfileIds[] vs filterInstitutionProfileIds[]).
        """
        params: dict[str, Any] = {
            "method": "presence.getPresenceTemplates",
            "filterInstitutionProfileIds[]": institution_profile_ids,
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        templates = _as_list(
            _response_data_object(resp).get("presenceWeekTemplates"),
            "data.presenceWeekTemplates",
            resp.status_code,
        )
        result = []
        skipped = _SkippedRecords("presence week template")
        for t in skipped.objects(templates):
            try:
                result.append(PresenceWeekTemplate.from_dict(t))
            except _RECORD_ERRORS as e:
                skipped.add(e, t)
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def update_presence_template(
        self,
        institution_profile_id: int,
        by_date: date,
        *,
        entry_time: str,
        exit_time: str,
        activity_type: ActivityType | int = ActivityType.PICKED_UP_BY,
        exit_with: str | None = None,
        comment: str | None = None,
        template_id: int | None = None,
        repeat_pattern: str = "Never",
        expires_at: str | None = None,
        self_decider_end_time: str | None = None,
    ) -> bool:
        """Create or update a presence template (planned entry/exit times).

        Args:
            institution_profile_id: Child's institution profile ID.
            by_date: The date for the template.
            entry_time: Arrival time in HH:mm format (e.g., "08:00").
            exit_time: Departure time in HH:mm format (e.g., "16:30"). For
                SELF_DECIDER, the earliest time the child may leave on their own.
            activity_type: How the child leaves at the end of the day. Prefer an
                ``ActivityType`` member; raw ints are accepted for compatibility.
            exit_with: Name of person picking up, including relation suffix
                (e.g., "Værge Et (Far)"). Required for PICKED_UP_BY and GO_HOME_WITH.
            comment: Optional daily comment/remark (empty string if not set).
            template_id: Existing template ID to update (None for new).
            repeat_pattern: "Never", "Weekly", or "Every2Weeks".
            expires_at: Expiration datetime in ISO format (e.g., "2026-06-26T00:00:00+00:00").
                If None, defaults to June 30 of the current school year.
            self_decider_end_time: The latest time a SELF_DECIDER child may leave,
                in HH:mm format, making a window from ``exit_time``. Defaults to
                ``exit_time``.

        Returns:
            True if the update was successful.

        Raises:
            ValueError: If ``self_decider_end_time`` is given for another
                activity type, which has no window to put it in.
        """
        # The Aula backend expects camelCase keys (CamelCasePropertyNamesContractResolver)
        # and enums: ActivityType as int, RepeatPattern as lowercase string.
        repeat_map = {
            "never": "never",
            "weekly": "weekly",
            "every2weeks": "every_2_weeks",
        }
        repeat_value = repeat_map.get(repeat_pattern.lower(), "never")

        # Default expiresAt to end of school year (June 30) if not provided
        if expires_at is None:
            year = by_date.year
            # If we're past June, the school year ends next June
            end_year = year + 1 if by_date.month > 6 else year
            expires_at = f"{end_year}-06-30T00:00:00+00:00"

        # Unknown ints fall through to the flat shape rather than raising, so a
        # newly-added Aula activity type still reaches the backend.
        activity_value = (
            activity_type.value if isinstance(activity_type, ActivityType) else activity_type
        )
        if self_decider_end_time is not None and activity_value != ActivityType.SELF_DECIDER.value:
            raise ValueError("self_decider_end_time is only used with ActivityType.SELF_DECIDER")

        # Build the activity sub-object based on activity_type
        activity: dict[str, Any] = {"activityType": activity_value}
        if activity_value == ActivityType.PICKED_UP_BY.value:
            activity["pickup"] = {
                "entryTime": entry_time,
                "exitTime": exit_time,
                "exitWith": exit_with or "",
            }
        elif activity_value == ActivityType.SELF_DECIDER.value:
            activity["selfDecider"] = {
                "entryTime": entry_time,
                "exitStartTime": exit_time,
                "exitEndTime": self_decider_end_time or exit_time,
            }
        elif activity_value == ActivityType.SEND_HOME.value:
            activity["sendHome"] = {
                "entryTime": entry_time,
                "exitTime": exit_time,
            }
        elif activity_value == ActivityType.GO_HOME_WITH.value:
            activity["goHomeWith"] = {
                "entryTime": entry_time,
                "exitTime": exit_time,
                "exitWith": exit_with or "",
            }
        else:
            activity["entryTime"] = entry_time
            activity["exitTime"] = exit_time

        payload: dict[str, Any] = {
            "institutionProfileId": institution_profile_id,
            "byDate": by_date.isoformat(),
            "presenceActivity": activity,
            "comment": comment or "",
            "repeatPattern": repeat_value,
            "expiresAt": expires_at,
        }
        if template_id is not None:
            payload["id"] = template_id

        resp = await self._request_with_version_retry(
            "post",
            f"{self.api_url}?method=presence.updatePresenceTemplate",
            json=payload,
        )
        resp.raise_for_status()
        return True

    async def update_presence_status(
        self,
        institution_profile_ids: list[int],
        status: PresenceState | int,
    ) -> bool:
        """Set today's presence status for children, e.g. report them sick.

        This is the endpoint behind the portal's sick button: reporting a child
        ill and taking the report back are the same call with a different status.
        The institution sees the change immediately.

        Aula has no future-dated sick report; this always applies to today. For a
        planned absence use :meth:`add_vacation` or :meth:`update_presence_template`
        instead.

        An institution can withhold this from guardians, in which case Aula
        rejects the call. :meth:`get_presence_configuration` reports that up
        front via ``PresenceConfiguration.can_edit(PresenceModule.REPORT_SICK)``.

        Args:
            institution_profile_ids: Children's institution profile IDs, i.e.
                ``Child.id``. Several children can be set in one call.
            status: The status to set. ``PresenceState.SICK`` reports a child
                sick. To take the report back the portal sends
                ``PresenceState.NOT_PRESENT`` from the guardian dashboard, and
                ``PresenceState.PRESENT`` from the presence page, so pick the one
                that matches the child's real situation. Raw ints are accepted so
                a status Aula adds later still reaches the backend.

        Returns:
            True if Aula accepted the change.

        Raises:
            ValueError: If no institution profile IDs are given.
        """
        if not institution_profile_ids:
            raise ValueError("update_presence_status requires at least one profile ID")

        status_value = status.value if isinstance(status, PresenceState) else status
        payload: dict[str, Any] = {
            "institutionProfileIds": institution_profile_ids,
            "status": status_value,
        }

        resp = await self._request_with_version_retry(
            "post",
            f"{self.api_url}?method=presence.updateStatusByInstitutionProfileIds",
            json=payload,
        )
        resp.raise_for_status()
        # The endpoint answers with a bare boolean in "data". Older/proxied
        # responses omit it, so absence is not treated as failure.
        data = _response_body(resp).get("data")
        return data if isinstance(data, bool) else True

    async def add_vacation(
        self,
        child_ids: list[int],
        start_date: date,
        end_date: date,
        comment: str = "",
    ) -> bool:
        """Register a planned absence ("ferie/fri") for children, as a guardian.

        The portal only offers this for children where
        ``PresenceConfiguration.can_edit(PresenceModule.VACATION)`` holds and
        ``Child.has_custody_or_extended_access`` is not False. This method checks
        neither; that is left to the caller.

        Args:
            child_ids: Children's institution profile IDs, i.e. ``Child.id``.
            start_date: First day of the absence, today or later in Denmark.
            end_date: End of the absence, sent to Aula as given. The same day as
                ``start_date`` for a single day, at most a calendar year later.
            comment: Note to the institution, at most 250 characters.

        Returns:
            True once Aula has accepted the absence. Aula's reply carries no
            documented ID for it.

        Raises:
            ValueError: If no child IDs are given or :func:`validate_vacation`
                rejects the dates or comment. Nothing is sent then.
        """
        if not child_ids:
            raise ValueError("add_vacation requires at least one child ID")
        validate_vacation(start_date, end_date, comment, today=aula_today())

        payload: dict[str, Any] = {
            "childIds": child_ids,
            "intervals": [
                {"startDate": start_date.isoformat(), "endDate": end_date.isoformat()},
            ],
            "comment": comment,
        }
        resp = await self._request_with_version_retry(
            "post",
            f"{self.api_url}?method=calendar.addVacation",
            json=payload,
        )
        resp.raise_for_status()
        return True

    async def get_pickup_responsibles(
        self,
        child_ids: list[int],
    ) -> list[ChildPickupResponsibles]:
        """Fetch pickup responsibles (family members + saved suggestions) for children.

        Args:
            child_ids: Institution profile IDs of the children (uniStudentIds).

        Returns:
            List of ChildPickupResponsibles, one per child.
        """
        params: dict[str, Any] = {
            "method": "presence.getPickupResponsibles",
            "uniStudentIds[]": child_ids,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_list(resp)
        result = []
        skipped = _SkippedRecords("pickup responsible")
        for item in skipped.objects(data):
            try:
                result.append(ChildPickupResponsibles.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def get_presence_registrations(
        self,
        institution_profile_ids: list[int],
        from_date: date,
        to_date: date,
    ) -> list[PresenceRegistration]:
        """Fetch presence registrations for the given profiles and date range.

        Aula rejects the whole batch when any one profile cannot be queried -
        a school child alongside a daycare child is enough to turn the request
        into an HTTP 400. Rather than lose every child's data to one of them,
        a failed batch is retried per profile and the profiles that still fail
        are skipped with a warning. The error is only raised when no profile
        can be read at all.
        """
        try:
            return await self._fetch_presence_registrations(
                institution_profile_ids, from_date, to_date
            )
        except HttpRequestError as e:
            if len(institution_profile_ids) <= 1:
                raise
            _LOGGER.warning(
                "Presence registrations failed for %d profiles at once (%s), retrying one by one",
                len(institution_profile_ids),
                e,
            )
            batch_error = e

        result: list[PresenceRegistration] = []
        failed: list[int] = []
        for profile_id in institution_profile_ids:
            try:
                result.extend(
                    await self._fetch_presence_registrations([profile_id], from_date, to_date)
                )
            except HttpRequestError as e:
                _LOGGER.debug(
                    "Presence registrations unavailable for profile %s: %s", profile_id, e
                )
                failed.append(profile_id)

        if len(failed) == len(institution_profile_ids):
            raise batch_error
        if failed:
            _LOGGER.warning(
                "Skipped presence registrations for profile(s) %s; "
                "their institution likely does not use the presence module",
                ", ".join(str(profile_id) for profile_id in failed),
            )
        return result

    async def _fetch_presence_registrations(
        self,
        institution_profile_ids: list[int],
        from_date: date,
        to_date: date,
    ) -> list[PresenceRegistration]:
        """Fetch presence registrations for exactly the profiles given."""
        params: dict[str, Any] = {
            "method": "presence.getPresenceRegistrations",
            "institutionProfileIds[]": institution_profile_ids,
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_list(resp)
        result = []
        skipped = _SkippedRecords("presence registration")
        for item in skipped.objects(data):
            try:
                result.append(PresenceRegistration.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def get_presence_registration_detail(
        self, registration_id: int
    ) -> PresenceRegistrationDetail | None:
        """Fetch detail for a single presence registration."""
        params: dict[str, Any] = {
            "method": "presence.getPresenceRegistrationDetail",
            "id": registration_id,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_object(resp)
        if not data:
            return None
        return _parse_object(
            PresenceRegistrationDetail.from_dict, data, "presence registration", resp.status_code
        )

    async def get_presence_states(
        self,
        institution_profile_ids: list[int] | None = None,
    ) -> list[ChildPresenceState]:
        """Fetch current presence states, optionally filtered by profile IDs."""
        params: dict[str, Any] = {
            "method": "presence.getPresenceStates",
        }
        if institution_profile_ids:
            params["institutionProfileIds[]"] = institution_profile_ids
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_list(resp)
        result = []
        skipped = _SkippedRecords("presence state")
        for item in skipped.objects(data):
            try:
                result.append(ChildPresenceState.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def get_presence_configuration(
        self,
        child_ids: list[int],
    ) -> list[PresenceConfiguration]:
        """Fetch presence configuration (pickup rules, etc.) by child IDs."""
        params: dict[str, Any] = {
            "method": "presence.getPresenceConfigurationByChildIds",
            "childIds[]": child_ids,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_list(resp)
        result = []
        skipped = _SkippedRecords("presence configuration")
        for item in skipped.objects(data):
            try:
                result.append(PresenceConfiguration.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def get_activity_overview(
        self,
        institution_profile_ids: list[int],
        week: int,
        year: int,
    ) -> PresenceWeekOverview | None:
        """Fetch the activity/week overview for presence."""
        params: dict[str, Any] = {
            "method": "presence.getActivityOverview",
            "institutionProfileIds[]": institution_profile_ids,
            "week": week,
            "year": year,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_object(resp)
        if not data:
            return None
        return _parse_object(
            PresenceWeekOverview.from_dict, data, "activity overview", resp.status_code
        )

    async def get_notifications_for_active_profile(
        self,
        *,
        children_ids: list[int] | None = None,
        institution_codes: list[str] | None = None,
        offset: int = 0,
        limit: int = 50,
        module: str | None = None,
    ) -> list[Notification]:
        """Fetch notifications for the active profile."""
        params: dict[str, Any] = {
            "method": "notifications.getNotificationsForActiveProfile",
            "offset": offset,
            "limit": limit,
        }
        if children_ids:
            params["activeChildrenIds[]"] = children_ids
        if institution_codes:
            params["activeInstitutionCodes[]"] = institution_codes
        if module:
            params["module"] = module

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        payload = _response_data_list(resp)

        notifications: list[Notification] = []
        skipped = _SkippedRecords("notification")
        for item in skipped.objects(payload):
            try:
                notifications.append(Notification.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(notifications, resp.status_code)
        if limit > 0:
            return notifications[:limit]
        return notifications

    async def get_message_threads(self, filter_on: str | None = None) -> list[MessageThread]:
        """Fetch the first page of message threads, sorted by date descending."""
        url = f"{self.api_url}?method=messaging.getThreads&sortOn=date&orderDirection=desc&page=0"
        if filter_on:
            url += f"&filterOn={filter_on}"
        resp = await self._request_with_version_retry("get", url)
        resp.raise_for_status()
        threads_data = _as_list(
            _response_data_object(resp).get("threads"), "data.threads", resp.status_code
        )

        threads = []
        skipped = _SkippedRecords("message thread")
        for t_dict in skipped.objects(threads_data):
            try:
                threads.append(MessageThread.from_dict(t_dict))
            except _RECORD_ERRORS as e:
                skipped.add(e, t_dict)
        skipped.raise_if_none_parsed(threads, resp.status_code)
        return threads

    async def get_messages_for_thread(self, thread_id: str, limit: int = 5) -> list[Message]:
        """Fetches the latest messages for a specific thread."""
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=messaging.getMessagesForThread&threadId={thread_id}&page=0&limit={limit}",
        )
        resp.raise_for_status()
        messages = []
        skipped = _SkippedRecords("message")
        raw_messages = _as_list(
            _response_data_object(resp).get("messages"), "data.messages", resp.status_code
        )

        for msg_dict in skipped.objects(raw_messages):
            if msg_dict.get("messageType") in ("Message", "MessageEdited"):
                try:
                    messages.append(Message.from_dict(msg_dict))
                except _RECORD_ERRORS as e:
                    skipped.add(e, msg_dict)
            if len(messages) >= limit:
                break

        skipped.raise_if_none_parsed(messages, resp.status_code)
        return messages

    @staticmethod
    def _api_data(resp: HttpResponse, api_method: str) -> dict[str, Any]:
        """Return the ``data`` object of an Aula answer, or raise when it is not a success.

        ``raise_for_status()`` only looks at the HTTP status, but Aula reports its own
        errors inside an HTTP 200: ``{"status": {"code": N, ...}, "data": ...}``, where
        ``code`` 0 is success. A body that is not that envelope is not trusted either.
        """
        resp.raise_for_status()
        body = _response_body(resp)
        status = body.get("status")
        if not isinstance(status, dict) or status.get("code") != 0:
            code = status.get("code") if isinstance(status, dict) else None
            raise HttpRequestError(
                f"Aula rejected {api_method} (status code {code})", resp.status_code
            )
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    def _thread_messages_url(self, thread_id: str, page: int, limit: int) -> str:
        """URL for one page of a thread's messages, on the API version in use now.

        Built on every call: a request can negotiate a newer API version, and a URL
        kept from before that would go to the old one.
        """
        return (
            f"{self.api_url}?method=messaging.getMessagesForThread"
            f"&threadId={thread_id}&page={page}&limit={limit}"
        )

    async def mark_thread_read(self, thread_id: str) -> bool:
        """Mark a message thread as read, up to and including its latest message.

        Aula keeps one read marker per thread: the ID of the last message read. This
        finds the newest message and moves the marker there, as the web client does
        when a thread is opened. The write is checked afterwards: the marker Aula
        reports for the thread must be the message that was sent.

        The newest message is taken from the first page that holds one. A message that
        arrives while this runs is not seen, so the marker goes on the newest message
        as it was when the thread was read, and that thread may still show as unread.

        A thread can begin with events (recipients added or removed) that are not
        messages, so pages of 20 are read until a message turns up, at most
        ``_MAX_THREAD_PAGES`` of them.

        Only threads in the guardian's own mailbox are handled. Common inboxes and OTP
        inboxes need an extra inbox ID in the call, which this does not send, so a
        thread whose mailbox is not shown to be the guardian's own is refused with
        ``ValueError`` instead of being marked in the wrong place.

        Args:
            thread_id: The thread to mark, as returned by ``get_message_threads()``.

        Returns:
            ``True`` when the marker was set, ``False`` when the thread holds no message
            that can be marked.

        Raises:
            HttpRequestError: When Aula rejects a call or does not confirm the write.
            ValueError: When the thread is not shown to be in the guardian's own mailbox.
            ThreadScanLimitError: When ``_MAX_THREAD_PAGES`` pages held no message and
                Aula says there are more.
        """
        newest: dict[str, Any] | None = None
        more = False
        for page in range(_MAX_THREAD_PAGES):
            resp = await self._request_with_version_retry(
                "get", self._thread_messages_url(thread_id, page, 20)
            )
            data = self._api_data(resp, "messaging.getMessagesForThread")
            owner = data.get("mailBoxOwner")
            if not isinstance(owner, dict) or owner.get("mailBoxOwnerType") != "institutionProfile":
                raise ValueError(
                    f"thread {thread_id} is not shown to be in your own mailbox, "
                    "and mark-read only handles those"
                )
            newest = next(
                (
                    m
                    for m in data.get("messages") or []
                    if isinstance(m, dict) and m.get("messageType") in _MARKABLE_MESSAGE_TYPES
                ),
                None,
            )
            more = bool(data.get("moreMessagesExist"))
            if newest is not None or not more:
                break
        if newest is None and more:
            raise ThreadScanLimitError(
                f"thread {thread_id} has no message in its first {_MAX_THREAD_PAGES} pages"
            )
        if newest is None or not newest.get("id"):
            return False

        resp = await self._request_with_version_retry(
            "post",
            f"{self.api_url}?method=messaging.setLastReadMessage",
            json={
                "threadId": thread_id,
                "messageId": newest["id"],
                "commonInboxId": None,
                "otpInboxId": None,
            },
        )
        self._api_data(resp, "messaging.setLastReadMessage")

        resp = await self._request_with_version_retry(
            "get", self._thread_messages_url(thread_id, 0, 1)
        )
        marker = self._api_data(resp, "messaging.getMessagesForThread").get("lastReadMessageId")
        if marker != newest["id"]:
            raise HttpRequestError(
                f"Aula did not confirm the read marker of thread {thread_id}", resp.status_code
            )
        return True

    async def get_calendar_events(
        self, institution_profile_ids: list[int], start: datetime, end: datetime
    ) -> list[CalendarEvent]:
        """Fetch events for inclusive whole days, preserving each bound's timezone.

        Time components are ignored. Raise ValueError before making a request
        if the start date is after the end date.
        """
        if start.date() > end.date():
            raise ValueError("start date must be on or before end date")

        data = {
            "instProfileIds": institution_profile_ids,
            "resourceIds": [],
            "start": start.strftime("%Y-%m-%d 00:00:00.0000%z"),
            "end": end.strftime("%Y-%m-%d 23:59:59.0000%z"),
        }

        resp = await self._request_with_version_retry(
            "post",
            f"{self.api_url}?method=calendar.getEventsByProfileIdsAndResourceIds",
            json=data,
        )

        resp.raise_for_status()
        events = []
        raw_events = _response_data_list(resp)

        skipped = _SkippedRecords("calendar event")
        for event in skipped.objects(raw_events):
            try:
                lesson = event.get("lesson") or {}

                teacher = self._find_participant_by_role(lesson, "primaryTeacher")
                substitute = self._find_participant_by_role(lesson, "substituteTeacher")

                has_substitute = lesson.get("lessonStatus", "").lower() == "substitute"
                location = get_in(event, "primaryResource.name")
                profiles = _profile_ids(event.get("belongsToProfiles"))

                events.append(
                    CalendarEvent(
                        id=event.get("id"),
                        title=event.get("title"),
                        start_datetime=self._parse_date(event.get("startDateTime")),
                        end_datetime=self._parse_date(event.get("endDateTime")),
                        teacher_name=teacher.get("teacherName", ""),
                        has_substitute=has_substitute,
                        substitute_name=substitute.get("teacherName"),
                        teacher_names=_teacher_names(lesson, "primaryTeacher"),
                        substitute_names=_teacher_names(lesson, "substituteTeacher"),
                        location=location,
                        belongs_to=next(iter(profiles), None),
                        belongs_to_profiles=profiles,
                        event_type=event.get("type"),
                        _raw=event,
                    )
                )
            except _RECORD_ERRORS as e:
                skipped.add(e, event)

        skipped.raise_if_none_parsed(events, resp.status_code)
        return merge_duplicate_lessons(events)

    async def get_calendar_events_by_child(
        self, child_ids: list[int], start: datetime, end: datetime
    ) -> dict[int, list[CalendarEvent]]:
        """Fetch children's calendars for inclusive whole days, as one list per child.

        Use Child.id (institution profile ID) and timezone-aware bounds. One
        calendar request covers every child. An event Aula returns for several of
        them, such as twins' shared lesson or a school event for siblings, is
        listed under each child it names.

        A parent meeting a child has booked shows at the booked slot instead of
        the days-long booking period. That takes one more request per child, made
        only when the range holds a meeting. If one fails, that child's meetings
        stay as the calendar shows them and the failure is logged; authentication
        errors still raise.

        Raise ValueError before making a request if a bound is naive or the start
        date is after the end date.
        """
        if start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("Calendar bounds must be timezone-aware")
        events = await self.get_calendar_events(child_ids, start, end)

        by_child: dict[int, list[CalendarEvent]] = {child_id: [] for child_id in child_ids}
        for event in events:
            for profile_id in dict.fromkeys(event.belongs_to_profiles):
                if profile_id in by_child:
                    by_child[profile_id].append(event)

        if not any(event.event_type in MEETING_TYPES for event in events):
            return by_child

        # The calendar read covers whole days; get_meeting_bookings ends exclusively.
        day_start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = end.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

        async def bookings_for(child_id: int) -> list[MeetingBooking]:
            try:
                return await self.get_meeting_bookings(child_id, day_start, day_end)
            except AulaAuthenticationError:
                raise
            except HttpRequestError as err:
                _LOGGER.warning("Could not fetch booked meetings for child %s: %s", child_id, err)
                return []

        bookings = await asyncio.gather(*(bookings_for(child_id) for child_id in by_child))
        return {
            child_id: replace_booked_meetings(child_events, child_bookings)
            for (child_id, child_events), child_bookings in zip(
                by_child.items(), bookings, strict=True
            )
        }

    async def get_meeting_bookings(
        self, child_id: int, start: datetime, end: datetime
    ) -> list[MeetingBooking]:
        """Fetch a child's booked parent meetings overlapping [start, end).

        Use Child.id (institution profile ID) and timezone-aware bounds. Returns
        actual appointments rather than the calendar row's booking period.
        Requests span at most 49 days, below the reported 50-day calendar limit
        even across a daylight-saving change. A failed chunk raises instead of
        returning an incomplete list. The ordinary calendar API is unchanged.
        """
        if start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("Meeting bounds must be timezone-aware")
        if end <= start:
            raise ValueError("Meeting end must be after start")
        rows: list[dict[str, Any]] = []
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=49), end)
            resp = await self._request_with_version_retry(
                "post",
                f"{self.api_url}?method=calendar.getEventsByProfileIdsAndResourceIds",
                json={
                    "instProfileIds": [child_id],
                    "resourceIds": [],
                    "start": cursor.strftime("%Y-%m-%d %H:%M:%S.%f%z"),
                    "end": chunk_end.strftime("%Y-%m-%d %H:%M:%S.%f%z"),
                },
            )
            resp.raise_for_status()
            body = _response_body(resp)
            if get_in(body, "status.code") != 0:
                raise HttpRequestError(
                    "Aula rejected the meeting calendar request", resp.status_code
                )
            data = body.get("data")
            if not isinstance(data, list):
                raise AulaResponseError(
                    "Aula returned invalid meeting calendar data", resp.status_code
                )
            rows.extend(data)
            cursor = chunk_end
        try:
            bookings = meeting_bookings(rows, child_id)
        except ValueError as e:
            raise AulaResponseError(str(e), resp.status_code) from e
        return [
            booking
            for booking in bookings
            if booking.end_datetime > start and booking.start_datetime < end
        ]

    async def get_calendar_event(
        self, event_id: int, occurrence_datetime: str | None = None
    ) -> dict | None:
        """Fetch a single calendar event by ID."""
        params: dict[str, Any] = {
            "method": "calendar.getEventById",
            "eventId": event_id,
        }
        if occurrence_datetime:
            params["occurrenceDateTime"] = occurrence_datetime

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        return _response_data_object(resp) or None

    async def get_important_dates(self, limit: int = 10, include_today: bool = True) -> list[dict]:
        """Fetch upcoming important dates."""
        params: dict[str, Any] = {
            "method": "calendar.getImportantDates",
            "limit": limit,
            "includeToday": include_today,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        return _response_data_list(resp)

    async def get_birthday_events(
        self, institution_codes: list[str], start: str, end: str
    ) -> list[dict]:
        """Fetch birthday events for institutions."""
        params: dict[str, Any] = {
            "method": "calendar.getBirthdayEventsForInstitutions",
            "InstCodes[]": institution_codes,
            "Start": start,
            "End": end,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        return _response_data_list(resp)

    async def get_birthday_events_for_group(
        self, group_id: int, start: str, end: str
    ) -> list[dict]:
        """Fetch birthday events for a group."""
        params: dict[str, Any] = {
            "method": "calendar.getBirthdayEventsForGroup",
            "groupId": group_id,
            "start": start,
            "end": end,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        return _response_data_list(resp)

    async def get_event_types(self, institution_codes: list[str] | None = None) -> list[dict]:
        """Fetch event types."""
        params: dict[str, Any] = {
            "method": "calendar.getEventTypes",
            "Type": "all",
        }
        if institution_codes:
            params["FilterInstitutionCodes[]"] = institution_codes

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        return _response_data_list(resp)

    async def get_daily_aggregated_events(
        self, institution_profile_ids: list[int], start: str, end: str
    ) -> list[dict]:
        """Fetch daily aggregated events."""
        params: dict[str, Any] = {
            "method": "calendar.getDailyAggregatedEvents",
            "InstProfileIds[]": institution_profile_ids,
            "Start": start,
            "End": end,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        return _response_data_list(resp)

    async def get_events_for_institutions(
        self, institution_codes: list[str], start: str, end: str
    ) -> list[dict]:
        """Fetch events for institutions."""
        params: dict[str, Any] = {
            "method": "calendar.getEventsForInstitutions",
            "Start": start,
            "End": end,
            "InstCodes[]": institution_codes,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        return _response_data_list(resp)

    async def get_daily_event_count_for_group(
        self, group_id: int, start: str, end: str
    ) -> list[dict]:
        """Fetch event count per day for a group."""
        params: dict[str, Any] = {
            "method": "calendar.getDailyEventCountForGroup",
            "GroupId": group_id,
            "Start": start,
            "End": end,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        return _response_data_list(resp)

    async def get_events_by_group(self, group_id: int, start: str, end: str) -> list[dict]:
        """Fetch events by group ID."""
        params: dict[str, Any] = {
            "method": "calendar.geteventsbygroupid",
            "groupId": group_id,
            "start": start,
            "end": end,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        return _response_data_list(resp)

    async def get_groups(
        self,
        institution_codes: list[str] | None = None,
        child_institution_profile_ids: list[int] | None = None,
    ) -> list[Group]:
        """Fetch the groups available in the logged-in user's context.

        The API accepts exactly one of the two filters and answers HTTP 400 if
        both are sent together. Mirroring the Aula web client: guardians filter
        by ``child_institution_profile_ids`` (which yields the children's own
        class and SFO groups), employees by ``institution_codes``. When both are
        given, the child filter wins.

        ``data`` comes back as a list of profile contexts, each carrying its own
        ``groups`` list; those are flattened and de-duplicated by group ID.

        Raises:
            ValueError: If neither filter is supplied.
        """
        params: dict[str, Any] = {"method": "groups.getGroupsByContext"}
        if child_institution_profile_ids:
            params["childInstitutionProfileIds[]"] = child_institution_profile_ids
        elif institution_codes:
            params["institutionCodes[]"] = institution_codes
        else:
            raise ValueError(
                "get_groups requires either institution_codes or child_institution_profile_ids"
            )

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        data = _response_body(resp).get("data")
        contexts = [data] if isinstance(data, dict) else _as_list(data, "data", resp.status_code)
        raw_groups: list[Any] = []
        for context in contexts:
            if isinstance(context, dict) and isinstance(context.get("groups"), list):
                raw_groups.extend(context["groups"])

        groups: list[Group] = []
        skipped = _SkippedRecords("group")
        seen_ids: set[Any] = set()
        for item in skipped.objects(raw_groups):
            try:
                if item["id"] in seen_ids:
                    continue
                seen_ids.add(item["id"])
                groups.append(Group.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(groups, resp.status_code)
        return groups

    async def get_group(self, group_id: int) -> Group | None:
        """Fetch a single group by ID."""
        params: dict[str, Any] = {
            "method": "groups.getGroupById",
            "groupId": group_id,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        data = _response_data_object(resp)
        if not data:
            return None
        return _parse_object(Group.from_dict, data, "group", resp.status_code)

    async def get_group_members(
        self,
        group_id: int,
        portal_roles: list[str] | None = None,
    ) -> list[GroupMember]:
        """Fetch members of a group."""
        params: dict[str, Any] = {
            "method": "groups.getMembershipsLight",
            "groupId": group_id,
        }
        if portal_roles:
            params["portalRoles[]"] = portal_roles

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        raw_members = _response_data_list(resp)

        members: list[GroupMember] = []
        skipped = _SkippedRecords("group member")
        for item in skipped.objects(raw_members):
            if "institutionProfileId" not in item:
                skipped.add(KeyError("institutionProfileId"), item)
                continue
            try:
                members.append(GroupMember.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(members, resp.status_code)
        return members

    async def get_posts(
        self,
        institution_profile_ids: list[int],
        page: int = 1,
        limit: int = 10,
    ) -> list[Post]:
        """Fetch posts from Aula."""
        params = {
            "method": "posts.getAllPosts",
            "parent": "profile",
            "index": (page - 1) * limit,
            "limit": limit,
            "institutionProfileIds[]": institution_profile_ids,
        }

        _LOGGER.debug("Fetching posts with params: %s", params)

        resp = await self._request_with_version_retry("get", self.api_url, params=params)

        resp.raise_for_status()

        posts_data = _as_list(
            _response_data_object(resp).get("posts"), "data.posts", resp.status_code
        )
        posts = []
        skipped = _SkippedRecords("post")

        for post_data in skipped.objects(posts_data):
            _LOGGER.debug("Processing post data: %s", post_data)
            missing = [key for key in ("id", "title") if key not in post_data]
            if missing:
                skipped.add(KeyError(", ".join(missing)), post_data)
                continue
            try:
                posts.append(Post.from_dict(post_data))
            except _RECORD_ERRORS as e:
                skipped.add(e, post_data)

        skipped.raise_if_none_parsed(posts, resp.status_code)
        return posts

    async def get_post(self, post_id: int) -> Post | None:
        """Fetch a single post by ID."""
        params = {
            "method": "posts.getById",
            "id": post_id,
        }

        _LOGGER.debug("Fetching post %s", post_id)

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        data = _response_data_object(resp)
        if not data:
            return None

        return _parse_object(Post.from_dict, data, "post", resp.status_code)

    async def get_comments(
        self,
        parent_type: str,
        parent_id: int,
        limit: int = 100,
    ) -> list[Comment]:
        """Fetch comments for a given parent (e.g. post)."""
        params = {
            "method": "comments.getComments",
            "ParentType": parent_type,
            "ParentId": parent_id,
            "Limit": limit,
        }

        _LOGGER.debug("Fetching comments for %s %s", parent_type, parent_id)

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        comments_data = _response_data_list(resp)
        comments = []
        skipped = _SkippedRecords("comment")

        for item in skipped.objects(comments_data):
            try:
                comments.append(Comment.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)

        skipped.raise_if_none_parsed(comments, resp.status_code)
        return comments

    async def get_mu_tasks(
        self,
        widget_id: str,
        child_filter: list[str],
        institution_filter: list[str],
        week: str,
        session_uuid: str,
    ) -> list[MUTask]:
        """Fetch Min Uddannelse tasks (opgaver) for the given week."""
        warnings.warn(
            "AulaApiClient.get_mu_tasks is deprecated; "
            "use AulaApiClient.widgets.get_mu_tasks instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.widgets.get_mu_tasks(
            widget_id=widget_id,
            child_filter=child_filter,
            institution_filter=institution_filter,
            week=week,
            session_uuid=session_uuid,
        )

    async def get_ugeplan(
        self,
        widget_id: str,
        child_filter: list[str],
        institution_filter: list[str],
        week: str,
        session_uuid: str,
    ) -> list[MUWeeklyPerson]:
        """Fetch Min Uddannelse weekly plans (ugebreve) for the given week."""
        warnings.warn(
            "AulaApiClient.get_ugeplan is deprecated; "
            "use AulaApiClient.widgets.get_ugeplan instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.widgets.get_ugeplan(
            widget_id=widget_id,
            child_filter=child_filter,
            institution_filter=institution_filter,
            week=week,
            session_uuid=session_uuid,
        )

    async def get_easyiq_weekplan(
        self, week: str, session_uuid: str, institution_filter: list[str], child_id: str
    ) -> list[Appointment]:
        """Fetch EasyIQ weekly plan appointments for a child."""
        warnings.warn(
            "AulaApiClient.get_easyiq_weekplan is deprecated; "
            "use AulaApiClient.widgets.get_easyiq_weekplan instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.widgets.get_easyiq_weekplan(
            week=week,
            session_uuid=session_uuid,
            institution_filter=institution_filter,
            child_id=child_id,
        )

    async def get_meebook_weekplan(
        self,
        child_filter: list[str],
        institution_filter: list[str],
        week: str,
        session_uuid: str,
    ) -> list[MeebookStudentPlan]:
        """Fetch Meebook weekly plan for children.

        Week format must be YYYY-Wnn (with leading zero), e.g. '2026-W08'.
        """
        warnings.warn(
            "AulaApiClient.get_meebook_weekplan is deprecated; "
            "use AulaApiClient.widgets.get_meebook_weekplan instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.widgets.get_meebook_weekplan(
            child_filter=child_filter,
            institution_filter=institution_filter,
            week=week,
            session_uuid=session_uuid,
        )

    async def get_momo_courses(
        self,
        children: list[str],
        institutions: list[str],
        session_uuid: str,
    ) -> list[MomoUserCourses]:
        """Fetch MoMo courses (forløb) for children."""
        warnings.warn(
            "AulaApiClient.get_momo_courses is deprecated; "
            "use AulaApiClient.widgets.get_momo_courses instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.widgets.get_momo_courses(
            children=children,
            institutions=institutions,
            session_uuid=session_uuid,
        )

    async def get_library_status(
        self,
        widget_id: str,
        children: list[str],
        institutions: list[str],
        session_uuid: str,
    ) -> LibraryStatus:
        """Fetch library status (loans, reservations) from Cicero."""
        warnings.warn(
            "AulaApiClient.get_library_status is deprecated; "
            "use AulaApiClient.widgets.get_library_status instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.widgets.get_library_status(
            widget_id=widget_id,
            children=children,
            institutions=institutions,
            session_uuid=session_uuid,
        )

    async def get_gallery_albums(
        self,
        institution_profile_ids: list[int],
        limit: int = 1000,
        *,
        index: int = 0,
        sort_on: str = "createdAt",
        order_direction: str = "desc",
        filter_by: str = "all",
    ) -> list[dict]:
        """Fetch gallery albums as raw dicts.

        Args:
            index: Pagination offset (default 0).
            sort_on: Sort field — "createdAt" or "title".
            order_direction: "asc" or "desc".
            filter_by: Filter mode — "all", "tagged", or "own".
        """
        params = {
            "method": "gallery.getAlbums",
            "index": index,
            "limit": limit,
            "sortOn": sort_on,
            "orderDirection": order_direction,
            "filterBy": filter_by,
            "filterInstProfileIds[]": institution_profile_ids,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_body(resp).get("data")
        if isinstance(data, dict):
            return _as_list(data.get("albums"), "data.albums", resp.status_code)
        return _as_list(data, "data", resp.status_code)

    async def get_album_pictures(
        self, institution_profile_ids: list[int], album_id: int, limit: int = 1000
    ) -> list[dict]:
        """Fetch pictures for a specific album as raw dicts."""
        params = {
            "method": "gallery.getMedia",
            "albumId": album_id,
            "index": 0,
            "limit": limit,
            "sortOn": "uploadedAt",
            "orderDirection": "desc",
            "filterBy": "all",
            "filterInstProfileIds[]": institution_profile_ids,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_body(resp).get("data")
        if isinstance(data, dict):
            return _as_list(data.get("results"), "data.results", resp.status_code)
        return _as_list(data, "data", resp.status_code)

    async def search_messages(
        self,
        institution_profile_ids: list[int],
        institution_codes: list[str],
        *,
        text: str = "",
        from_date: date | None = None,
        to_date: date | None = None,
        has_attachments: bool | None = None,
        limit: int = 100,
    ) -> list[Message]:
        """Search all messages; use search_messages_result() for completeness.

        Profile IDs must contain children only, as including a parent can
        cause Aula to reject the request. ``limit`` is the page size.
        """
        result = await self.search_messages_result(
            institution_profile_ids,
            institution_codes,
            text=text,
            from_date=from_date,
            to_date=to_date,
            has_attachments=has_attachments,
            limit=limit,
        )
        self._warn_incomplete("search_messages", result)
        return result.items

    async def search_messages_result(
        self,
        institution_profile_ids: list[int],
        institution_codes: list[str],
        *,
        text: str = "",
        from_date: date | None = None,
        to_date: date | None = None,
        has_attachments: bool | None = None,
        limit: int = 100,
    ) -> PaginationResult[Message]:
        """Search messages with completeness metadata; limit is a positive page size."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        state = PaginationState(id_path="searchMessage.id")
        offset = 0
        reason = "max_pages"
        for _page in range(MAX_PAGES):
            payload = {
                "text": text,
                "typeahead": False,
                "exactTerm": True,
                "activeChildrenInstitutionProfileIds": institution_profile_ids,
                "institutionCodes": institution_codes,
                "limit": limit,
                "offset": offset,
                "commonInboxID": None,
                "filterBy": "all",
                "sortBy": "date",
                "sortDirection": "desc",
                "threadSubject": None,
                "messageContent": None,
                "fromDate": from_date.isoformat() + "T00:00:00" if from_date else None,
                "toDate": to_date.isoformat() + "T23:59:59" if to_date else None,
                "threadCreators": [],
                "participants": [],
                "hasAttachments": has_attachments,
            }

            resp = await self._request_with_version_retry(
                "post",
                f"{self.api_url}?method=search.findMessage",
                json=payload,
            )
            resp.raise_for_status()
            data = _response_data_object(resp)
            state.observe_total(data)
            rows = _as_list(data.get("results"), "data.results", resp.status_code)
            if not rows:
                reason = "exhausted"
                break
            if not state.add(rows):
                reason = "no_progress"
                break
            offset += limit
            if (state.total is not None and offset >= state.total) or len(rows) < limit:
                reason = "exhausted"
                break
        result = state.result(reason)
        messages: list[Message] = []
        skipped = _SkippedRecords("search hit")
        for row in skipped.objects(result.items):
            try:
                messages.append(Message.from_search_hit(row))
            except _RECORD_ERRORS as e:
                skipped.add(e, row)
        skipped.raise_if_none_parsed(messages, resp.status_code)
        return PaginationResult(messages, result.complete, result.termination_reason)

    @staticmethod
    def _warn_incomplete(operation: str, result: PaginationResult) -> None:
        if not result.complete:
            _LOGGER.warning(
                "%s returning partial results (%s, MAX_PAGES=%d)",
                operation,
                result.termination_reason,
                MAX_PAGES,
            )

    async def get_all_message_threads(self, cutoff_date: date) -> list[dict]:
        """Read threads in first-seen order; warn if the read is incomplete."""
        result = await self.get_all_message_threads_result(cutoff_date)
        self._warn_incomplete("get_all_message_threads", result)
        return result.items

    async def get_all_message_threads_result(self, cutoff_date: date) -> PaginationResult[dict]:
        """Read threads until a date cutoff, with explicit completeness metadata."""
        state = PaginationState()
        for page in range(MAX_PAGES):
            resp = await self._request_with_version_retry(
                "get",
                f"{self.api_url}?method=messaging.getThreads&sortOn=date&orderDirection=desc&page={page}",
            )
            resp.raise_for_status()
            data = _response_data_object(resp)
            state.observe_total(data)
            threads = _as_list(data.get("threads"), "data.threads", resp.status_code)
            if not threads:
                return state.result("exhausted")
            eligible = []
            cutoff_reached = False
            for thread in _SkippedRecords("message thread").objects(threads):
                last_updated = MessageThread.from_dict(thread).last_updated
                if last_updated and last_updated.date() < cutoff_date:
                    cutoff_reached = True
                    break
                eligible.append(thread)
            progressed = state.add(eligible) if eligible else False
            if cutoff_reached:
                return state.result("cutoff")
            if not progressed:
                return state.result("no_progress")
        return state.result("max_pages")

    async def get_all_messages_for_thread(self, thread_id: str) -> list[dict]:
        """Read all thread messages; warn if the read is incomplete."""
        result = await self.get_all_messages_for_thread_result(thread_id)
        self._warn_incomplete("get_all_messages_for_thread", result)
        return result.items

    async def get_all_messages_for_thread_result(self, thread_id: str) -> PaginationResult[dict]:
        """Read a thread's full history with explicit completeness metadata."""
        state = PaginationState()
        for page in range(MAX_PAGES):
            resp = await self._request_with_version_retry(
                "get",
                f"{self.api_url}?method=messaging.getMessagesForThread&threadId={thread_id}&page={page}",
            )
            resp.raise_for_status()
            data = _response_data_object(resp)
            state.observe_total(data)
            messages = _as_list(data.get("messages"), "data.messages", resp.status_code)
            if not messages:
                return state.result("exhausted")
            if not state.add(messages):
                return state.result("no_progress")
        return state.result("max_pages")

    async def download_file(self, url: str, *, max_bytes: int | None = None) -> bytes:
        """Download a file as raw bytes.

        Raises ``DownloadTooLargeError`` when the file is larger than ``max_bytes``.
        """
        return await self._client.download_bytes(url, max_bytes=max_bytes)

    async def get_widget_token(self, widget_id: str) -> str:
        """Mint a widget token for ``widget_id`` from the Aula session.

        Returns the raw JWT, with no ``Bearer `` prefix: each provider puts it
        in its own header. Raises ``AulaResponseError`` when the answer holds no token.
        """
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=aulaToken.getAulaToken&widgetId={widget_id}",
        )
        resp.raise_for_status()
        token = _response_body(resp).get("data")
        if not isinstance(token, str) or not token:
            raise AulaResponseError("Aula answered without a widget token", resp.status_code)
        return token

    def _parse_date(self, date_str: str) -> datetime:
        return datetime.fromisoformat(date_str).astimezone(ZoneInfo("Europe/Copenhagen"))

    def _find_participant_by_role(self, lesson: dict[str, Any], role: str) -> dict[str, Any]:
        participants = lesson.get("participants", [])

        return next(
            (x for x in participants if x.get("participantRole") == role),
            {},
        )

    async def get_message_folders(self, include_deleted: bool = False) -> list[MessageFolder]:
        """Fetch message folders."""
        params: dict[str, Any] = {
            "method": "messaging.getFolders",
            "IncludeDeletedFolders": include_deleted,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        raw = _response_data_list(resp)
        folders: list[MessageFolder] = []
        skipped = _SkippedRecords("message folder")
        for item in skipped.objects(raw):
            if "id" not in item:
                skipped.add(KeyError("id"), item)
                continue
            try:
                folders.append(MessageFolder.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(folders, resp.status_code)
        return folders

    async def get_common_inboxes(
        self, institution_profile_ids: list[int] | None = None
    ) -> list[dict]:
        """Fetch common inboxes."""
        params: dict[str, Any] = {
            "method": "messaging.getCommonInboxes",
        }
        if institution_profile_ids:
            params["InstitutionProfileIds[]"] = institution_profile_ids
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        return _response_data_list(resp)

    async def get_threads_in_bundle(self, bundle_id: int) -> list[MessageThread]:
        """Fetch threads in a bundle."""
        params: dict[str, Any] = {
            "method": "messaging.getThreadsInBundle",
            "BundleId": bundle_id,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        raw = _response_data_list(resp)
        threads: list[MessageThread] = []
        skipped = _SkippedRecords("bundle thread")
        for item in skipped.objects(raw):
            try:
                threads.append(MessageThread.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(threads, resp.status_code)
        return threads

    async def get_message_info(self, thread_id: str, message_id: str) -> dict | None:
        """Fetch lightweight message info."""
        params: dict[str, Any] = {
            "method": "messaging.getMessageInfoLight",
            "ThreadId": thread_id,
            "MessageId": message_id,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        return _response_data_object(resp) or None

    async def find_recipients(
        self,
        text: str,
        limit: int = 100,
        doc_types: str | None = None,
        portal_roles: list[str] | None = None,
    ) -> list[dict]:
        """Find message recipients."""
        params: dict[str, Any] = {
            "method": "search.findRecipients",
            "Text": text,
            "Limit": limit,
            "TypeAhead": "true",
        }
        if doc_types:
            params["DocTypes"] = doc_types
        if portal_roles:
            params["PortalRoles"] = portal_roles
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        return _as_list(
            _response_data_object(resp).get("results"), "data.results", resp.status_code
        )

    async def find_profiles_and_groups(self, text: str, limit: int = 100) -> dict:
        """Find profiles and groups."""
        params: dict[str, Any] = {
            "method": "search.findProfilesAndGroups",
            "Text": text,
            "Limit": limit,
            "Typeahead": "true",
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        return _response_data_object(resp)

    async def search(
        self, text: str, doc_type: str | None = None, limit: int = 20, offset: int = 0
    ) -> dict:
        """Global search."""
        params: dict[str, Any] = {
            "method": "search.findGeneric",
            "Text": text,
            "Limit": limit,
            "Offset": offset,
            "DocTypeCount": "true",
        }
        if doc_type:
            params["DocType"] = doc_type
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        return _response_data_object(resp)

    async def get_contact_list(
        self,
        group_id: int,
        page: int = 1,
        order: str = "asc",
        profile_type: str = "guardian",
        field: str = "name",
    ) -> list[dict]:
        """Fetch the contact list for a group.

        The API method name is ``profiles.getContactlist`` (lowercase ``l``) and
        every parameter here is required: omitting ``filter``, ``field``,
        ``page`` or ``order`` answers HTTP 400, as does ``page=0`` (pages are
        1-based).

        Args:
            group_id: Group to list contacts for.
            page: 1-based page number; each page holds up to 20 contacts.
            order: ``asc`` or ``desc``.
            profile_type: Which profiles to return - ``child``, ``boy``,
                ``girl``, ``guardian`` or ``employee``. Note that a group only
                returns contacts for the types it actually contains, so a
                parents-only group yields nothing for ``child``.
            field: Field to sort by (``name``).
        """
        params: dict[str, Any] = {
            "method": "profiles.getContactlist",
            "groupId": group_id,
            "filter": profile_type,
            "field": field,
            "page": page,
            "order": order,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        return _response_data_list(resp)

    async def get_contact_parents(self, page: int = 1, order: str = "asc") -> list[dict]:
        """Fetch other parents.

        Both parameters are required by the API; omitting them answers HTTP 400.
        Accounts without access to the "other parents" list get HTTP 403.

        Args:
            page: 1-based page number.
            order: ``asc`` or ``desc``.
        """
        params: dict[str, Any] = {
            "method": "profiles.getContactParents",
            "page": page,
            "order": order,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        return _response_data_list(resp)

    async def get_media_by_id(self, media_id: int) -> dict | None:
        """Fetch a single media item by ID."""
        params: dict[str, Any] = {
            "method": "gallery.getMediaById",
            "id": media_id,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        return _response_data_object(resp) or None

    async def get_media_by_profile(
        self, institution_profile_id: int, limit: int = 100
    ) -> list[dict]:
        """Fetch media tagged with a profile."""
        params: dict[str, Any] = {
            "method": "gallery.getMediaByInstitutionProfileId",
            "institutionProfileId": institution_profile_id,
            "Limit": limit,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        return _response_data_list(resp)

    async def keep_alive(self) -> bool:
        """Extend the backend session to prevent timeouts."""
        try:
            resp = await self._request_with_version_retry(
                "get", f"{self.api_url}?method=profiles.keepAlive"
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            _LOGGER.warning("Keep-alive failed: %s", e)
            return False

    async def get_profile_master_data(
        self, institution_profile_id: int
    ) -> ProfileMasterData | None:
        """Fetch extended profile master data (email, phone, address)."""
        params: dict[str, Any] = {
            "method": "profiles.getProfileMasterData",
            "institutionProfileId": institution_profile_id,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_object(resp)
        if not data:
            return None
        try:
            return ProfileMasterData.from_dict(data)
        except (TypeError, ValueError, KeyError) as e:
            _LOGGER.warning("Failed to parse profile master data: %s", e)
            return None

    async def get_consent_responses(
        self, institution_profile_ids: list[int]
    ) -> list[ConsentResponse]:
        """Fetch consent responses for the given institution profile IDs."""
        params: dict[str, Any] = {
            "method": "consents.getConsentResponses",
            "institutionProfileIds[]": institution_profile_ids,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_list(resp)
        result: list[ConsentResponse] = []
        skipped = _SkippedRecords("consent response")
        for item in skipped.objects(data):
            try:
                result.append(ConsentResponse.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def get_auto_reply(self) -> AutoReply | None:
        """Fetch the current auto-reply configuration."""
        params: dict[str, Any] = {
            "method": "messaging.getAutoReply",
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_object(resp)
        if not data:
            return None
        try:
            return AutoReply.from_dict(data)
        except (TypeError, ValueError, KeyError) as e:
            _LOGGER.warning("Failed to parse auto-reply: %s", e)
            return None

    async def search_groups(self, text: str, limit: int = 100) -> list[Group]:
        """Search for groups by name."""
        params: dict[str, Any] = {
            "method": "search.findGroups",
            "text": text,
            "limit": limit,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        results = _as_list(
            _response_data_object(resp).get("results"), "data.results", resp.status_code
        )
        groups: list[Group] = []
        skipped = _SkippedRecords("group search result")
        for item in skipped.objects(results):
            try:
                groups.append(Group.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(groups, resp.status_code)
        return groups

    async def get_secure_documents(
        self, institution_profile_ids: list[int], page_size: int = 20
    ) -> list[SecureDocument]:
        """Fetch every secure document shared with the user.

        Pass the user's own institution profile IDs. Aula answers 403 when a
        child's institution profile ID is included.
        """
        result: list[SecureDocument] = []
        skipped = _SkippedRecords("secure document")
        seen = 0
        while True:
            resp = await self._request_with_version_retry(
                "post",
                f"{self.api_url}?method=documents.getSecureDocuments",
                json={
                    "index": seen,
                    "limit": page_size,
                    "filterInstitutionProfileIds": institution_profile_ids,
                },
            )
            resp.raise_for_status()
            data = _response_data_object(resp)
            batch = _as_list(data.get("documents"), "data.documents", resp.status_code)
            if not batch:
                break

            seen += len(batch)
            for item in skipped.objects(batch):
                try:
                    result.append(SecureDocument.from_dict(item))
                except _RECORD_ERRORS as e:
                    skipped.add(e, item)

            if not data.get("moreDocumentsExists"):
                break
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def get_common_files(
        self, institution_codes: list[str], page_size: int = 20
    ) -> list[CommonFile]:
        """Fetch every common file the given institutions share.

        A guardian passes the institution codes of their children's schools.
        """
        if not institution_codes:
            return []

        result: list[CommonFile] = []
        skipped = _SkippedRecords("common file")
        seen = 0
        while True:
            params: dict[str, Any] = {
                "method": "commonFiles.getCommonFiles",
                "index": seen,
                "limit": page_size,
                "institutionCodes[]": institution_codes,
            }
            resp = await self._request_with_version_retry("get", self.api_url, params=params)
            resp.raise_for_status()
            data = _response_data_object(resp)
            batch = _as_list(data.get("commonFiles"), "data.commonFiles", resp.status_code)
            total = data.get("totalAmount")
            if not batch:
                break

            seen += len(batch)
            for item in skipped.objects(batch):
                try:
                    result.append(CommonFile.from_dict(item))
                except _RECORD_ERRORS as e:
                    skipped.add(e, item)

            if not isinstance(total, int) or seen >= total:
                break
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def get_vacation_registrations(self, child_ids: list[int]) -> list[VacationRegistration]:
        """Fetch vacation registrations for the given children.

        Args:
            child_ids: Institution profile IDs of the children (`Child.id`). Passing
                a guardian's own institution profile ID, or a child's user profile
                ID, makes Aula reject the request.

        Aula groups the response by child; the rows are flattened into a single
        list with the child carried on each registration.
        """
        params: dict[str, Any] = {
            "method": "presence.getVacationRegistrationsByChildren",
            "childIds[]": child_ids,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_list(resp)
        result: list[VacationRegistration] = []
        skipped = _SkippedRecords("vacation registration")
        for group in data:
            if not isinstance(group, dict):
                continue
            child = group.get("child")
            child = child if isinstance(child, dict) else {}
            registrations = group.get("vacationRegistrations")
            if not isinstance(registrations, list):
                continue
            for item in skipped.objects(registrations):
                try:
                    result.append(VacationRegistration.from_dict(item, child))
                except _RECORD_ERRORS as e:
                    skipped.add(e, item)
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def get_notification_settings(self) -> list[NotificationSetting]:
        """Fetch notification settings for the active profile."""
        params: dict[str, Any] = {
            "method": "notifications.getNotificationSettingsForActiveProfile",
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = _response_data_list(resp)
        result: list[NotificationSetting] = []
        skipped = _SkippedRecords("notification setting")
        for item in skipped.objects(data):
            try:
                result.append(NotificationSetting.from_dict(item))
            except _RECORD_ERRORS as e:
                skipped.add(e, item)
        skipped.raise_if_none_parsed(result, resp.status_code)
        return result

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.close()
