import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .const import (
    API_URL,
    API_VERSION,
    CICERO_API,
    EASYIQ_API,
    MIN_UDDANNELSE_API,
    SYSTEMATIC_API,
    WIDGET_EASYIQ,
    WIDGET_HUSKELISTEN,
)
from .http import HttpClient, HttpResponse
from .models import (
    Appointment,
    CalendarEvent,
    Child,
    DailyOverview,
    LibraryStatus,
    Message,
    MessageThread,
    MUTask,
    MUWeeklyPerson,
    Post,
    Profile,
)

# Logger
_LOGGER = logging.getLogger(__name__)


class AulaApiClient:
    """Async client for Aula API endpoints.

    Transport-agnostic: accepts any HttpClient implementation (httpx, aiohttp, etc.).
    Authentication is handled externally; this client only needs a ready HTTP
    transport and a valid access token.
    """

    def __init__(self, http_client: HttpClient, access_token: str) -> None:
        self._client = http_client
        self._access_token = access_token
        self.api_url = f"{API_URL}{API_VERSION}"

    async def init(self) -> None:
        """Discover the current API version and establish guardian role."""
        await self._set_correct_api_version()

        # Establish guardian role in the session (required for child-specific endpoints)
        await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=profiles.getProfileContext&portalrole=guardian",
        )

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
        params: dict | list[tuple[str, str]] | None = None,
        json: object | None = None,
    ) -> HttpResponse:
        """Make an HTTP request with automatic API version bump on 410 Gone.

        Automatically appends the access_token query parameter for Aula API URLs.
        """
        # Auto-append access token for Aula API requests
        if self._access_token and url.startswith(API_URL):
            if params is not None:
                params["access_token"] = self._access_token
            else:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}access_token={self._access_token}"

        max_retries = 5
        for _attempt in range(max_retries):
            response = await self._client.request(
                method, url, headers=headers, params=params, json=json
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
            ip.get("id") for ip in profile_dict.get("institutionProfiles", [])
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
        except Exception as e:
            _LOGGER.debug("is_logged_in check failed: %s", e)
            return False
        return True

    async def get_profile_context(self) -> dict:
        """Fetch the profile context for the current guardian session."""
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=profiles.getProfileContext&portalrole=guardian",
        )
        resp.raise_for_status()
        return resp.json()

    async def get_daily_overview(self, child_id: int) -> DailyOverview | None:
        """Fetches the daily overview for a specific child.

        Returns None if the data is unavailable (e.g. 403 Forbidden).
        """
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=presence.getDailyOverview&childIds[]={child_id}",
        )
        if resp.status_code != 200:
            _LOGGER.warning(
                "Could not fetch daily overview for child %d: HTTP %d",
                child_id,
                resp.status_code,
            )
            return None
        data = resp.json().get("data")
        if not data:
            _LOGGER.warning("No daily overview data for child %d", child_id)
            return None
        return DailyOverview.from_dict(data[0])

    async def get_message_threads(self) -> list[MessageThread]:
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=messaging.getThreads&sortOn=date&orderDirection=desc&page=0",
        )
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
            if msg_dict.get("messageType") == "Message":
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
        data = {
            "instProfileIds": institution_profile_ids,
            "resourceIds": [],
            "start": start.strftime("%Y-%m-%d 00:00:00.0000%z"),
            "end": end.strftime("%Y-%m-%d 23:59:59.0000%z"),
        }

        req_headers = {"content-type": "application/json"}
        csrf_token = self._client.get_cookie("Csrfp-Token")
        if csrf_token:
            req_headers["csrfp-token"] = csrf_token

        resp = await self._request_with_version_retry(
            "post",
            f"{self.api_url}?method=calendar.getEventsByProfileIdsAndResourceIds",
            headers=req_headers,
            json=data,
        )

        resp.raise_for_status()
        data = resp.json()

        events = []
        raw_events = data.get("data", [])
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

    async def get_mu_tasks(
        self,
        widget_id: str,
        child_filter: list[str],
        institution_filter: list[str],
        week: str,
        session_uuid: str,
    ) -> list[MUTask]:
        """Fetch Min Uddannelse tasks (opgaver) for the given week."""
        token = await self._get_bearer_token(widget_id)
        params: list[tuple[str, str]] = [
            ("placement", "narrow"),
            ("sessionUUID", session_uuid),
            ("userProfile", "guardian"),
            ("currentWeekNumber", week),
            ("isMobileApp", "false"),
        ]
        for child in child_filter:
            params.append(("childFilter[]", child))
        for inst in institution_filter:
            params.append(("institutionFilter[]", inst))

        resp = await self._request_with_version_retry(
            "get",
            f"{MIN_UDDANNELSE_API}/opgaveliste",
            params=params,
            headers={"Authorization": token, "Accept": "application/json"},
        )
        return [MUTask.from_dict(o) for o in resp.json().get("opgaver", [])]

    async def get_ugeplan(
        self,
        widget_id: str,
        child_filter: list[str],
        institution_filter: list[str],
        week: str,
        session_uuid: str,
    ) -> list[MUWeeklyPerson]:
        """Fetch Min Uddannelse weekly plans (ugebreve) for the given week."""
        token = await self._get_bearer_token(widget_id)
        params = {
            "assuranceLevel": "3",
            "childFilter": ",".join(child_filter),
            "currentWeekNumber": week,
            "institutionFilter": ",".join(institution_filter),
            "isMobileApp": "false",
            "placement": "narrow",
            "sessionUUID": session_uuid,
            "userProfile": "guardian",
        }
        resp = await self._request_with_version_retry(
            "get",
            f"{MIN_UDDANNELSE_API}/ugebrev",
            params=params,
            headers={"Authorization": token, "Accept": "application/json"},
        )
        return [MUWeeklyPerson.from_dict(p) for p in resp.json().get("personer", [])]

    async def get_easyiq_weekplan(
        self, week: str, session_uuid: str, institution_filter: list[str], child_id: str
    ) -> Appointment:
        token = await self._get_bearer_token(WIDGET_EASYIQ)
        headers = {
            "Authorization": token,
            "x-aula-institutionfilter": ",".join(institution_filter),
        }
        payload = {
            "sessionId": session_uuid,
            "currentWeekNr": week,
            "userProfile": "guardian",
            "institutionFilter": institution_filter,
            "childFilter": [child_id],
        }
        resp = await self._request_with_version_retry(
            "post", f"{EASYIQ_API}/weekplaninfo", json=payload, headers=headers
        )
        return self._parse_appointment(resp)

    async def get_huskeliste(self, children: list[str], institutions: list[str]) -> Appointment:
        token = await self._get_bearer_token(WIDGET_HUSKELISTEN)
        params = {
            "children": ",".join(children),
            "institutions": ",".join(institutions),
        }
        resp = await self._request_with_version_retry(
            "get",
            f"{SYSTEMATIC_API}/reminders/v1",
            params=params,
            headers={"Aula-Authorization": token},
        )
        return self._parse_appointment(resp)

    async def get_library_status(
        self,
        widget_id: str,
        children: list[str],
        institutions: list[str],
        session_uuid: str,
    ) -> LibraryStatus:
        """Fetch library status (loans, reservations) from Cicero."""
        token = await self._get_bearer_token(widget_id)
        params: list[tuple[str, str]] = [
            ("coverImageHeight", "160"),
            ("widgetVersion", "1.6"),
            ("userProfile", "guardian"),
            ("sessionUUID", session_uuid),
        ]
        for inst in institutions:
            params.append(("institutions", inst))
        for child in children:
            params.append(("children", child))

        resp = await self._request_with_version_retry(
            "get",
            f"{CICERO_API}/library/status/v3",
            params=params,
            headers={"Authorization": token, "Accept": "application/json"},
        )
        return LibraryStatus.from_dict(resp.json())

    def _parse_appointment(self, resp: HttpResponse) -> Appointment:
        """Extract the first appointment from a widget API response."""
        appointments = resp.json().get("data", {}).get("appointments", [])
        if not appointments:
            raise ValueError("No appointments found in widget response")
        appointment = appointments[0]
        return Appointment(
            _raw=appointment,
            appointment_id=appointment.get("appointmentId"),
            title=appointment.get("title"),
        )

    async def _get_bearer_token(self, widget_id: str) -> str:
        resp = await self._request_with_version_retry(
            "get", f"{self.api_url}?method=aulaToken.getAulaToken&widgetId={widget_id}"
        )
        token = "Bearer " + str(resp.json()["data"])
        return token

    def _parse_date(self, date_str: str) -> datetime:
        return datetime.fromisoformat(date_str).astimezone(ZoneInfo("Europe/Copenhagen"))

    def _find_participant_by_role(self, lesson: dict, role: str):
        participants = lesson.get("participants", [])

        return next(
            (x for x in participants if x.get("participantRole") == role),
            {},
        )

    async def __aenter__(self) -> "AulaApiClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.close()
