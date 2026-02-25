import logging
import time
from datetime import date, datetime
from types import TracebackType
from typing import Any
from zoneinfo import ZoneInfo

from .const import (
    API_URL,
    API_VERSION,
    CICERO_API,
    EASYIQ_API,
    MEEBOOK_API,
    MIN_UDDANNELSE_API,
    SYSTEMATIC_API,
    WIDGET_EASYIQ,
    WIDGET_HUSKELISTEN,
    WIDGET_MEEBOOK,
)
from .http import HttpClient, HttpRequestError, HttpResponse
from .models import (
    Appointment,
    CalendarEvent,
    Child,
    DailyOverview,
    LibraryStatus,
    MeebookStudentPlan,
    Message,
    MessageThread,
    MomoUserCourses,
    MUTask,
    MUWeeklyPerson,
    Post,
    PresenceWeekTemplate,
    Profile,
)

# Logger
_LOGGER = logging.getLogger(__name__)

# Safety limit for paginated requests to prevent infinite loops
MAX_PAGES = 100


class AulaApiClient:
    """Async client for Aula API endpoints.

    Transport-agnostic: accepts any HttpClient implementation (httpx, aiohttp, etc.).
    Authentication is handled externally; this client only needs a ready HTTP
    transport and a valid access token.
    """

    def __init__(
        self,
        http_client: HttpClient,
        access_token: str,
        csrf_token: str | None = None,
    ) -> None:
        self._client = http_client
        self._access_token = access_token
        self._csrf_token = csrf_token
        self.api_url = f"{API_URL}{API_VERSION}"

    async def init(self) -> None:
        """Discover the current API version and establish guardian role."""
        await self._set_correct_api_version()

        # Establish guardian role in the session (required for child-specific endpoints)
        await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=profiles.getProfileContext&portalrole=guardian",
        )

        # Capture CSRF token set by the server during the session setup.
        # The Csrfp-Token cookie is not part of the stored auth credentials;
        # it's set by Aula via Set-Cookie during these initial GET requests.
        if self._csrf_token is None:
            self._csrf_token = self._client.get_cookie("Csrfp-Token")

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

        Automatically appends the access_token query parameter for Aula API URLs.
        """
        # Auto-append access token for Aula API requests
        if self._access_token and url.startswith(API_URL):
            if params is not None:
                params = {**params, "access_token": self._access_token}
            else:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}access_token={self._access_token}"

        max_retries = 5
        for _attempt in range(max_retries):
            start = time.monotonic()
            response = await self._client.request(
                method, url, headers=headers, params=params, json=json
            )
            elapsed = time.monotonic() - start

            _LOGGER.debug(
                "%s %s → %d (%.2fs)",
                method.upper(),
                url.split("?")[0],
                response.status_code,
                elapsed,
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

    async def get_message_threads(
        self, filter_on: str | None = None
    ) -> list[MessageThread]:
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

        req_headers = {"content-type": "application/json"}
        if self._csrf_token:
            req_headers["csrfp-token"] = self._csrf_token

        resp = await self._request_with_version_retry(
            "post",
            f"{self.api_url}?method=calendar.getEventsByProfileIdsAndResourceIds",
            headers=req_headers,
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
        params = {
            "placement": "narrow",
            "sessionUUID": session_uuid,
            "userProfile": "guardian",
            "currentWeekNumber": week,
            "isMobileApp": "false",
            "childFilter[]": child_filter,
            "institutionFilter[]": institution_filter,
        }

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
    ) -> list[Appointment]:
        """Fetch EasyIQ weekly plan appointments for a child."""
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
        appointments = resp.json().get("data", {}).get("appointments", [])
        return [
            Appointment(
                _raw=a,
                appointment_id=a.get("appointmentId"),
                title=a.get("title"),
            )
            for a in appointments
        ]

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
        token = await self._get_bearer_token(WIDGET_MEEBOOK)

        # Ensure week number has leading zero (YYYY-Wnn format)
        parts = week.split("-W")
        if len(parts) == 2:
            week = f"{parts[0]}-W{int(parts[1]):02d}"

        params = {
            "currentWeekNumber": week,
            "userProfile": "guardian",
            "childFilter[]": child_filter,
            "institutionFilter[]": institution_filter,
        }

        headers = {
            "Authorization": token,
            "Accept": "application/json",
            "sessionUUID": session_uuid,
            "X-Version": "1.0",
        }

        resp = await self._request_with_version_retry(
            "get",
            f"{MEEBOOK_API}/relatedweekplan/all",
            params=params,
            headers=headers,
        )
        return [MeebookStudentPlan.from_dict(s) for s in resp.json()]

    async def get_momo_courses(
        self,
        children: list[str],
        institutions: list[str],
        session_uuid: str,
    ) -> list[MomoUserCourses]:
        """Fetch MoMo courses (forløb) for children."""
        token = await self._get_bearer_token(WIDGET_HUSKELISTEN)

        params = {
            "widgetVersion": "1.3",
            "userProfile": "guardian",
            "sessionId": session_uuid,
            "children": children,
            "institutions": institutions,
        }

        resp = await self._request_with_version_retry(
            "get",
            f"{SYSTEMATIC_API}/courses/v1",
            params=params,
            headers={"Aula-Authorization": token},
        )
        return [MomoUserCourses.from_dict(u) for u in resp.json()]

    async def get_library_status(
        self,
        widget_id: str,
        children: list[str],
        institutions: list[str],
        session_uuid: str,
    ) -> LibraryStatus:
        """Fetch library status (loans, reservations) from Cicero."""
        token = await self._get_bearer_token(widget_id)
        params = {
            "coverImageHeight": "160",
            "widgetVersion": "1.6",
            "userProfile": "guardian",
            "sessionUUID": session_uuid,
            "institutions": institutions,
            "children": children,
        }

        resp = await self._request_with_version_retry(
            "get",
            f"{CICERO_API}/library/status/v3",
            params=params,
            headers={"Authorization": token, "Accept": "application/json"},
        )
        return LibraryStatus.from_dict(resp.json())

    async def get_gallery_albums(
        self, institution_profile_ids: list[int], limit: int = 1000
    ) -> list[dict]:
        """Fetch gallery albums as raw dicts."""
        params = {
            "method": "gallery.getAlbums",
            "index": 0,
            "limit": limit,
            "sortOn": "createdAt",
            "orderDirection": "desc",
            "filterBy": "all",
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
        headers: dict[str, str] = {"content-type": "application/json"}
        if self._csrf_token:
            headers["csrfp-token"] = self._csrf_token

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
                headers=headers,
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
        resp = await self._request_with_version_retry(
            "get", f"{self.api_url}?method=aulaToken.getAulaToken&widgetId={widget_id}"
        )
        token = "Bearer " + str(resp.json()["data"])
        return token

    def _parse_date(self, date_str: str) -> datetime:
        return datetime.fromisoformat(date_str).astimezone(ZoneInfo("Europe/Copenhagen"))

    def _find_participant_by_role(self, lesson: dict[str, Any], role: str) -> dict[str, Any]:
        participants = lesson.get("participants", [])

        return next(
            (x for x in participants if x.get("participantRole") == role),
            {},
        )

    async def __aenter__(self) -> "AulaApiClient":
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
