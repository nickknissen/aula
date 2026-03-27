import inspect
import json
import logging
import time
import warnings
from datetime import date, datetime
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
from .http import HttpClient, HttpRequestError, HttpResponse
from .models import (
    Appointment,
    AutoReply,
    CalendarEvent,
    Child,
    ChildPickupResponsibles,
    ChildPresenceState,
    Comment,
    ConsentResponse,
    DailyOverview,
    Group,
    GroupMember,
    LibraryStatus,
    MeebookStudentPlan,
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
    PresenceWeekOverview,
    PresenceWeekTemplate,
    Profile,
    ProfileMasterData,
    SecureDocument,
    VacationRegistration,
    WidgetConfiguration,
)
from .widgets import AulaWidgetsClient

# Logger
_LOGGER = logging.getLogger(__name__)

# Safety limit for paginated requests to prevent infinite loops
MAX_PAGES = 100


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


def _compact_payload_for_log(payload: Any, *, max_chars: int = 4000) -> str:
    try:
        rendered = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        rendered = str(payload)
    if len(rendered) > max_chars:
        return f"{rendered[:max_chars]}...<truncated>"
    return rendered


class AulaApiClient:
    """Async client for Aula API endpoints.

    Transport-agnostic: accepts any HttpClient implementation (httpx, aiohttp, etc.).
    Authentication uses ``access_token`` as a query parameter during ``init()``
    to establish a server-side session, then relies on session cookies for all
    subsequent API requests.
    """

    def __init__(
        self,
        http_client: HttpClient,
        access_token: str | None = None,
        csrf_token: str | None = None,
    ) -> None:
        self._client = http_client
        self._access_token = access_token
        self._csrf_token = csrf_token
        self.api_url = f"{API_URL}{API_VERSION}"
        self.widgets: AulaWidgetsClient = AulaWidgetsClient(self)

    async def init(self) -> None:
        """Discover the current API version and establish guardian role.

        Uses ``access_token`` as a query parameter for these initial requests
        to establish a server-side session. After init completes, the access
        token is cleared and all subsequent requests rely on session cookies.
        """
        await self._set_correct_api_version()

        # Establish guardian role in the session (required for child-specific endpoints)
        await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=profiles.getProfileContext&portalrole=guardian",
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
                    "Response method=%s: %s",
                    api_method or "unknown",
                    _compact_payload_for_log(response.json()),
                )

            if response.status_code == 410:
                current_version = int(self.api_url.split("/v")[-1])
                new_version = current_version + 1

                _LOGGER.warning(
                    "API version v%d is deprecated (410 Gone), automatically switching to v%d",
                    current_version,
                    new_version,
                )

                self.api_url = f"{API_URL}{new_version}"
                url = url.replace(f"/v{current_version}", f"/v{new_version}")
                continue

            return response

        raise RuntimeError(f"Failed to find working API version after {max_retries} attempts")

    async def get_profile(self) -> Profile:
        """Fetch the authenticated user's profile with children.

        Raises:
            HttpRequestError: If the API returns a 4xx/5xx error.
            ValueError: If no profile data is found.
        """
        resp = await self._request_with_version_retry(
            "get", f"{self.api_url}?method=profiles.getProfilesByLogin"
        )
        resp.raise_for_status()
        raw_data_list = resp.json().get("data", {}).get("profiles", [])

        if not raw_data_list:
            raise ValueError("No profile data found in API response")

        profile_dict = raw_data_list[0]

        children = []
        raw_children = profile_dict.get("children", [])
        if isinstance(raw_children, list):
            for child_dict in raw_children:
                if not isinstance(child_dict, dict):
                    continue
                try:
                    children.append(Child.from_dict(child_dict))
                except (TypeError, ValueError) as e:
                    _LOGGER.warning(
                        "Skipping child due to parsing error: %s - Data: %s", e, child_dict
                    )

        institution_profile_ids = [
            ip["id"] for ip in profile_dict.get("institutionProfiles", []) if "id" in ip
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
            _LOGGER.error("Failed to parse main profile: %s - Data: %s", e, profile_dict)
            raise ValueError("Failed to parse main profile data") from e

        return profile

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
        return resp.json()

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
        data = resp.json()
        widget_configs = (
            data.get("data", {}).get("pageConfiguration", {}).get("widgetConfigurations", [])
        )
        widgets = []
        for item in widget_configs:
            try:
                w = WidgetConfiguration.from_dict(item)
                if w.aggregated_display_mode == "Shown":
                    widgets.append(w)
            except Exception:
                _LOGGER.warning("Failed to parse widget configuration: %s", item)
        return widgets

    async def get_daily_overview(self, child_id: int) -> DailyOverview | None:
        """Fetches the daily overview for a specific child.

        Returns None if no data is available for the child.

        Raises:
            HttpRequestError: If the API returns a 4xx/5xx error.
        """
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=presence.getDailyOverview&childIds[]={child_id}",
        )
        resp.raise_for_status()
        data = resp.json().get("data")
        if not data:
            _LOGGER.warning("No daily overview data for child %d", child_id)
            return None
        return DailyOverview.from_dict(data[0])

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
        data = resp.json().get("data")
        if not isinstance(data, dict):
            return []
        templates = data.get("presenceWeekTemplates", [])
        if not isinstance(templates, list):
            return []
        result = []
        for t in templates:
            if t is None or not isinstance(t, dict):
                continue
            try:
                result.append(PresenceWeekTemplate.from_dict(t))
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                _LOGGER.warning(
                    "Skipping presence week template due to parsing error: %s - Data: %s", e, t
                )
        return result

    async def update_presence_template(
        self,
        institution_profile_id: int,
        by_date: date,
        *,
        entry_time: str,
        exit_time: str,
        activity_type: int = 0,
        exit_with: str | None = None,
        comment: str | None = None,
        template_id: int | None = None,
        repeat_pattern: str = "Never",
        expires_at: str | None = None,
    ) -> bool:
        """Create or update a presence template (planned entry/exit times).

        Args:
            institution_profile_id: Child's institution profile ID.
            by_date: The date for the template.
            entry_time: Arrival time in HH:mm format (e.g., "08:00").
            exit_time: Departure time in HH:mm format (e.g., "16:30").
            activity_type: Activity type enum value (0=PICKED_UP_BY, 1=SELF_DECIDER,
                2=SEND_HOME, 3=GO_HOME_WITH, 4=DROP_OFF_TIME).
            exit_with: Name of person picking up, including relation suffix
                (e.g., "Nick Hansen (Far)"). Required for PICKED_UP_BY and GO_HOME_WITH.
            comment: Optional daily comment/remark (empty string if not set).
            template_id: Existing template ID to update (None for new).
            repeat_pattern: "Never", "Weekly", or "Every2Weeks".
            expires_at: Expiration datetime in ISO format (e.g., "2026-06-26T00:00:00+00:00").
                If None, defaults to June 30 of the current school year.

        Returns:
            True if the update was successful.
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

        # Build the activity sub-object based on activity_type
        activity: dict[str, Any] = {"activityType": activity_type}
        if activity_type == 0:  # PICKED_UP_BY
            activity["pickup"] = {
                "entryTime": entry_time,
                "exitTime": exit_time,
                "exitWith": exit_with or "",
            }
        elif activity_type == 1:  # SELF_DECIDER
            activity["selfDecider"] = {
                "entryTime": entry_time,
                "exitStartTime": exit_time,
                "exitEndTime": exit_time,
            }
        elif activity_type == 2:  # SEND_HOME
            activity["sendHome"] = {
                "entryTime": entry_time,
                "exitTime": exit_time,
            }
        elif activity_type == 3:  # GO_HOME_WITH
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
        data = resp.json().get("data")
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if item is None or not isinstance(item, dict):
                continue
            try:
                result.append(ChildPickupResponsibles.from_dict(item))
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                _LOGGER.warning("Skipping pickup responsible due to parsing error: %s", e)
        return result

    async def get_presence_registrations(
        self,
        institution_profile_ids: list[int],
        from_date: date,
        to_date: date,
    ) -> list[PresenceRegistration]:
        """Fetch presence registrations for the given profiles and date range."""
        params: dict[str, Any] = {
            "method": "presence.getPresenceRegistrations",
            "institutionProfileIds[]": institution_profile_ids,
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                result.append(PresenceRegistration.from_dict(item))
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                _LOGGER.warning(
                    "Skipping presence registration due to parsing error: %s - Data: %s", e, item
                )
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
        data = resp.json().get("data")
        if not isinstance(data, dict):
            return None
        return PresenceRegistrationDetail.from_dict(data)

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
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                result.append(ChildPresenceState.from_dict(item))
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                _LOGGER.warning(
                    "Skipping presence state due to parsing error: %s - Data: %s", e, item
                )
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
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                result.append(PresenceConfiguration.from_dict(item))
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                _LOGGER.warning(
                    "Skipping presence configuration due to parsing error: %s - Data: %s", e, item
                )
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
        data = resp.json().get("data")
        if not isinstance(data, dict):
            return None
        return PresenceWeekOverview.from_dict(data)

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

        payload = resp.json().get("data", [])
        if not isinstance(payload, list):
            return []

        notifications: list[Notification] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                notifications.append(Notification.from_dict(item))
            except (TypeError, ValueError) as e:
                _LOGGER.warning(
                    "Skipping notification due to parsing error: %s - Data: %s", e, item
                )
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
        threads_data = resp.json().get("data", {}).get("threads", [])

        threads = []
        for t_dict in threads_data:
            try:
                thread = MessageThread(
                    thread_id=t_dict.get("id"),
                    subject=t_dict.get("subject"),
                    _raw=t_dict,
                )
                threads.append(thread)
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning(
                    "Skipping message thread due to initialization error: %s - Data: %s",
                    e,
                    t_dict,
                )
        return threads

    async def get_messages_for_thread(self, thread_id: str, limit: int = 5) -> list[Message]:
        """Fetches the latest messages for a specific thread."""
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=messaging.getMessagesForThread&threadId={thread_id}&page=0&limit={limit}",
        )
        resp.raise_for_status()
        data = resp.json()
        messages = []
        raw_messages = data.get("data", {}).get("messages", [])

        for msg_dict in raw_messages:
            if msg_dict.get("messageType") in ("Message", "MessageEdited"):
                try:
                    text = msg_dict.get("text", {}).get("html") or msg_dict.get("text", "")
                    messages.append(
                        Message(_raw=msg_dict, id=msg_dict.get("id"), content_html=text)
                    )
                except (TypeError, ValueError) as e:
                    _LOGGER.warning(
                        "Skipping message due to parsing error: %s - Data: %s", e, msg_dict
                    )
            if len(messages) >= limit:
                break

        return messages

    async def get_calendar_events(
        self, institution_profile_ids: list[int], start: datetime, end: datetime
    ) -> list[CalendarEvent]:
        """Fetch calendar events for the given profiles and date range."""
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
        response_data = resp.json()

        events = []
        raw_events = response_data.get("data", [])
        if not isinstance(raw_events, list):
            _LOGGER.warning("Unexpected data format for calendar events: %s", raw_events)
            return []

        for event in raw_events:
            try:
                lesson = event.get("lesson", {}) or {}

                teacher = self._find_participant_by_role(lesson, "primaryTeacher")
                substitute = self._find_participant_by_role(lesson, "substituteTeacher")

                has_substitute = lesson.get("lessonStatus", "").lower() == "substitute"
                location = lesson.get("primaryResource", {}).get("name")

                events.append(
                    CalendarEvent(
                        id=event.get("id"),
                        title=event.get("title"),
                        start_datetime=self._parse_date(event.get("startDateTime")),
                        end_datetime=self._parse_date(event.get("endDateTime")),
                        teacher_name=teacher.get("teacherName", ""),
                        has_substitute=has_substitute,
                        substitute_name=substitute.get("teacherName"),
                        location=location,
                        belongs_to=next(iter(event.get("belongsToProfiles", [])), None),
                        _raw=event,
                    )
                )
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning(
                    "Skipping calendar event due to initialization error: %s - Data: %s",
                    e,
                    event,
                )
                continue

        return events

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

        data = resp.json().get("data", {})
        if not data or not isinstance(data, dict):
            return None
        return data

    async def get_important_dates(self, limit: int = 10, include_today: bool = True) -> list[dict]:
        """Fetch upcoming important dates."""
        params: dict[str, Any] = {
            "method": "calendar.getImportantDates",
            "limit": limit,
            "includeToday": include_today,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

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

        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

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

        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

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

        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

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

        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

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

        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

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

        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

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

        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

    async def get_groups(
        self,
        institution_codes: list[str],
        child_institution_profile_ids: list[int],
    ) -> list[Group]:
        """Fetch groups for the given institution codes and child profile IDs."""
        params: dict[str, Any] = {
            "method": "groups.getGroupsByContext",
            "InstitutionCodes[]": institution_codes,
            "ChildInstitutionProfileIds[]": child_institution_profile_ids,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        raw_groups = resp.json().get("data", {}).get("groups", [])
        if not isinstance(raw_groups, list):
            return []

        groups: list[Group] = []
        for item in raw_groups:
            try:
                if not isinstance(item, dict) or "id" not in item:
                    _LOGGER.warning("Skipping invalid group data: %s", item)
                    continue
                groups.append(Group.from_dict(item))
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning("Skipping group due to parsing error: %s - Data: %s", e, item)
                continue
        return groups

    async def get_group(self, group_id: int) -> Group | None:
        """Fetch a single group by ID."""
        params: dict[str, Any] = {
            "method": "groups.getGroupById",
            "groupId": group_id,
        }

        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()

        data = resp.json().get("data", {})
        if not data or not isinstance(data, dict):
            return None
        return Group.from_dict(data)

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

        raw_members = resp.json().get("data", [])
        if not isinstance(raw_members, list):
            return []

        members: list[GroupMember] = []
        for item in raw_members:
            try:
                if not isinstance(item, dict) or "institutionProfileId" not in item:
                    _LOGGER.warning("Skipping invalid group member data: %s", item)
                    continue
                members.append(GroupMember.from_dict(item))
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning(
                    "Skipping group member due to parsing error: %s - Data: %s", e, item
                )
                continue
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
            "index": page - 1,
            "limit": limit,
            "institutionProfileIds[]": institution_profile_ids,
        }

        _LOGGER.debug("Fetching posts with params: %s", params)

        resp = await self._request_with_version_retry("get", self.api_url, params=params)

        resp.raise_for_status()

        posts_data = resp.json().get("data", {}).get("posts", [])
        posts = []

        for post_data in posts_data:
            try:
                if not isinstance(post_data, dict):
                    _LOGGER.warning("Skipping non-dict post data: %s", post_data)
                    continue

                _LOGGER.debug("Processing post data: %s", post_data)

                if "id" in post_data and "title" in post_data:
                    posts.append(Post.from_dict(post_data))
                else:
                    _LOGGER.warning(
                        "Skipping invalid post data (missing required fields): %s",
                        post_data,
                    )
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning(
                    "Skipping post due to parsing error: %s - Data: %s",
                    e,
                    post_data,
                    exc_info=_LOGGER.isEnabledFor(logging.DEBUG),
                )
                continue

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

        data = resp.json().get("data", {})
        if not data:
            return None

        return Post.from_dict(data)

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

        comments_data = resp.json().get("data", [])
        comments = []

        for item in comments_data:
            try:
                if not isinstance(item, dict):
                    _LOGGER.warning("Skipping non-dict comment data: %s", item)
                    continue
                comments.append(Comment.from_dict(item))
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning(
                    "Skipping comment due to parsing error: %s - Data: %s",
                    e,
                    item,
                    exc_info=_LOGGER.isEnabledFor(logging.DEBUG),
                )
                continue

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
        data = resp.json().get("data", [])
        if isinstance(data, list):
            return data
        return data.get("albums", [])

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
        data = resp.json().get("data", [])
        if isinstance(data, list):
            return data
        return data.get("results", [])

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
        """Search messages using search.findMessage with server-side filtering.

        ``institution_profile_ids`` must only contain the children's
        institution profile IDs (not the parent's), otherwise the API returns 403.

        Paginates automatically to fetch all matching results.
        """
        all_messages: list[Message] = []
        offset = 0
        pages_fetched = 0

        while True:
            if pages_fetched >= MAX_PAGES:
                _LOGGER.warning(
                    "search_messages hit MAX_PAGES limit (%d), returning partial results",
                    MAX_PAGES,
                )
                break

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
            data = resp.json().get("data", {})
            results = data.get("results", [])
            if not results:
                break

            for msg_dict in results:
                raw_text = msg_dict.get("text")
                if isinstance(raw_text, dict):
                    content_html = raw_text.get("html", "")
                elif isinstance(raw_text, str):
                    content_html = raw_text
                else:
                    content_html = ""
                all_messages.append(
                    Message(_raw=msg_dict, id=msg_dict.get("id", ""), content_html=content_html)
                )

            total = data.get("totalSize", 0)
            offset += limit
            pages_fetched += 1

            if offset >= total or len(results) < limit:
                break

        return all_messages

    async def get_all_message_threads(self, cutoff_date: date) -> list[dict]:
        """Paginate messaging.getThreads until threads are older than cutoff_date."""
        all_threads: list[dict] = []
        page = 0
        while page < MAX_PAGES:
            resp = await self._request_with_version_retry(
                "get",
                f"{self.api_url}?method=messaging.getThreads&sortOn=date&orderDirection=desc&page={page}",
            )
            resp.raise_for_status()
            threads = resp.json().get("data", {}).get("threads", [])
            if not threads:
                break

            for t in threads:
                last_date_str = t.get("lastMessageDate") or t.get("lastUpdatedDate", "")
                if last_date_str:
                    try:
                        thread_date = datetime.fromisoformat(last_date_str).date()
                        if thread_date < cutoff_date:
                            return all_threads
                    except (ValueError, TypeError):
                        pass
                all_threads.append(t)

            page += 1
        else:
            _LOGGER.warning(
                "get_all_message_threads hit MAX_PAGES limit (%d), returning partial results",
                MAX_PAGES,
            )

        return all_threads

    async def get_all_messages_for_thread(self, thread_id: str) -> list[dict]:
        """Paginate messaging.getMessagesForThread to get all messages."""
        all_messages: list[dict] = []
        page = 0
        while page < MAX_PAGES:
            resp = await self._request_with_version_retry(
                "get",
                f"{self.api_url}?method=messaging.getMessagesForThread&threadId={thread_id}&page={page}",
            )
            resp.raise_for_status()
            messages = resp.json().get("data", {}).get("messages", [])
            if not messages:
                break

            all_messages.extend(messages)
            page += 1
        else:
            _LOGGER.warning(
                "get_all_messages_for_thread hit MAX_PAGES limit (%d), returning partial results",
                MAX_PAGES,
            )

        return all_messages

    async def download_file(self, url: str) -> bytes:
        """Download a file as raw bytes."""
        return await self._client.download_bytes(url)

    async def _get_bearer_token(self, widget_id: str) -> str:
        return await self.widgets._get_bearer_token(widget_id)

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
        raw = resp.json().get("data", [])
        if not isinstance(raw, list):
            return []
        folders: list[MessageFolder] = []
        for item in raw:
            try:
                if not isinstance(item, dict) or "id" not in item:
                    continue
                folders.append(MessageFolder.from_dict(item))
            except (TypeError, ValueError, KeyError):
                continue
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
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

    async def get_threads_in_bundle(self, bundle_id: int) -> list[MessageThread]:
        """Fetch threads in a bundle."""
        params: dict[str, Any] = {
            "method": "messaging.getThreadsInBundle",
            "BundleId": bundle_id,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        raw = resp.json().get("data", [])
        if not isinstance(raw, list):
            return []
        threads: list[MessageThread] = []
        for item in raw:
            try:
                if not isinstance(item, dict):
                    continue
                threads.append(MessageThread.from_dict(item))
            except (TypeError, ValueError, KeyError):
                continue
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
        data = resp.json().get("data", {})
        if not data or not isinstance(data, dict):
            return None
        return data

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
        data = resp.json().get("data", {}).get("results", [])
        if not isinstance(data, list):
            return []
        return data

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
        return resp.json().get("data", {})

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
        return resp.json().get("data", {})

    async def get_contact_list(
        self, group_id: int, page: int | None = None, order: str | None = None
    ) -> list[dict]:
        """Fetch contact list for a group."""
        params: dict[str, Any] = {
            "method": "profiles.getContactList",
            "GroupId": group_id,
        }
        if page is not None:
            params["Page"] = page
        if order:
            params["Order"] = order
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

    async def get_contact_parents(
        self, page: int | None = None, order: str | None = None
    ) -> list[dict]:
        """Fetch other parents."""
        params: dict[str, Any] = {
            "method": "profiles.getContactParents",
        }
        if page is not None:
            params["Page"] = page
        if order:
            params["Order"] = order
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

    async def get_media_by_id(self, media_id: int) -> dict | None:
        """Fetch a single media item by ID."""
        params: dict[str, Any] = {
            "method": "gallery.getMediaById",
            "id": media_id,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        if not data or not isinstance(data, dict):
            return None
        return data

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
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        return data

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
        data = resp.json().get("data")
        if not data or not isinstance(data, dict):
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
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        result: list[ConsentResponse] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                result.append(ConsentResponse.from_dict(item))
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning("Skipping consent response due to parsing error: %s", e)
        return result

    async def get_auto_reply(self) -> AutoReply | None:
        """Fetch the current auto-reply configuration."""
        params: dict[str, Any] = {
            "method": "messaging.getAutoReply",
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data")
        if not data or not isinstance(data, dict):
            return None
        try:
            return AutoReply.from_dict(data)
        except (TypeError, ValueError, KeyError) as e:
            _LOGGER.warning("Failed to parse auto-reply: %s", e)
            return None

    async def search_groups(self, text: str, limit: int = 100) -> list[Group]:
        """Search for groups by name."""
        params: dict[str, Any] = {
            "method": "search.searchGroups",
            "Text": text,
            "Limit": limit,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        results = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            return []
        groups: list[Group] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                groups.append(Group.from_dict(item))
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning("Skipping group from search due to parsing error: %s", e)
        return groups

    async def get_secure_documents(
        self, institution_profile_ids: list[int]
    ) -> list[SecureDocument]:
        """Fetch secure documents shared with/by the user."""
        params: dict[str, Any] = {
            "method": "secureDocument.getSecureDocuments",
            "institutionProfileIds[]": institution_profile_ids,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        result: list[SecureDocument] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                result.append(SecureDocument.from_dict(item))
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning("Skipping document due to parsing error: %s", e)
        return result

    async def get_common_files(self, institution_profile_ids: list[int]) -> list[SecureDocument]:
        """Fetch common institution files."""
        params: dict[str, Any] = {
            "method": "secureDocument.getCommonFiles",
            "institutionProfileIds[]": institution_profile_ids,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        result: list[SecureDocument] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                result.append(SecureDocument.from_dict(item))
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning("Skipping common file due to parsing error: %s", e)
        return result

    async def get_vacation_registrations(
        self, institution_profile_ids: list[int]
    ) -> list[VacationRegistration]:
        """Fetch vacation registrations for the given institution profile IDs."""
        params: dict[str, Any] = {
            "method": "presence.getVacationRegistrations",
            "institutionProfileIds[]": institution_profile_ids,
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        result: list[VacationRegistration] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                result.append(VacationRegistration.from_dict(item))
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning("Skipping vacation registration due to parsing error: %s", e)
        return result

    async def get_notification_settings(self) -> list[NotificationSetting]:
        """Fetch notification settings for the active profile."""
        params: dict[str, Any] = {
            "method": "notifications.getNotificationSettingsForActiveProfile",
        }
        resp = await self._request_with_version_retry("get", self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not isinstance(data, list):
            return []
        result: list[NotificationSetting] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                result.append(NotificationSetting.from_dict(item))
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning("Skipping notification setting due to parsing error: %s", e)
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
