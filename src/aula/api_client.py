import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .auth import AulaAuthenticationError, MitIDAuthClient
from .const import (
    API_URL,
    API_VERSION,
    EASYIQ_API,
    MIN_UDDANNELSE_API,
    SYSTEMATIC_API,
    USER_AGENT,
)
from .models import (
    Appointment,
    CalendarEvent,
    Child,
    DailyOverview,
    Message,
    MessageThread,
    Post,
    Profile,
    ProfileContext,
)
from .token_storage import TokenStorage

# Logger
_LOGGER = logging.getLogger(__name__)


class AulaApiClient:
    """
    Async client for Aula API endpoints and parsing.

    Now uses MitID authentication instead of the old UniLogin system.
    Requires a MitID username and the MitID app for authentication.
    """

    def __init__(self, mitid_username: str, token_storage: TokenStorage):
        """
        Initialize the Aula API client.

        Args:
            mitid_username: Your MitID username (not Aula username)
            token_storage: A TokenStorage backend for persisting auth tokens.
        """
        self.mitid_username = mitid_username
        self._token_storage = token_storage
        self.api_url = f"{API_URL}{API_VERSION}"
        self._client: httpx.AsyncClient | None = None
        self._auth_client: MitIDAuthClient | None = None
        self._access_token: str | None = None

    async def login(self) -> None:
        """
        Authenticate using MitID and discover latest API URL.

        This method will:
        1. Try to load cached tokens from the token file
        2. If tokens are missing or expired, perform MitID authentication
           (requires MitID app approval)
        3. Configure the HTTP client with the access token
        4. Discover the current API version
        """
        self._auth_client = MitIDAuthClient(mitid_username=self.mitid_username)

        # Try to load cached tokens
        token_data = await self._token_storage.load()
        tokens_valid = False

        if token_data is not None:
            tokens = token_data.get("tokens", {})
            expires_at = tokens.get("expires_at")
            if tokens.get("access_token") and (expires_at is None or time.time() < expires_at):
                self._auth_client.tokens = tokens
                tokens_valid = True
                _LOGGER.info("Loaded cached authentication tokens")
            else:
                _LOGGER.info("Cached tokens are expired")

        if not tokens_valid:
            _LOGGER.info("No valid tokens found, starting MitID authentication...")
            _LOGGER.info("Please approve the login request in your MitID app")

            try:
                await self._auth_client.authenticate()
                await self._token_storage.save(
                    {
                        "timestamp": time.time(),
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "username": self.mitid_username,
                        "tokens": self._auth_client.tokens,
                    }
                )
                _LOGGER.info("Authentication successful! Tokens saved.")
            except AulaAuthenticationError as e:
                _LOGGER.error(f"Authentication failed: {e}")
                raise RuntimeError(f"MitID authentication failed: {e}")

        self._access_token = self._auth_client.access_token

        # Initialize HTTP client with authentication
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

        # Copy cookies from auth client to API client
        self._client.cookies = self._auth_client.cookies

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

    async def _request_with_version_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        Make an HTTP request with automatic API version bump on 410 Gone.

        If the API returns 410 Gone (deprecated version), automatically increment
        the version number and retry the request with the new version.

        Automatically appends the access_token query parameter for Aula API URLs.
        """
        # Auto-append access token for Aula API requests
        if self._access_token and url.startswith(API_URL):
            params = kwargs.get("params")
            if params is not None:
                params["access_token"] = self._access_token
            else:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}access_token={self._access_token}"

        max_retries = 5
        for attempt in range(max_retries):
            response = await getattr(self._client, method.lower())(url, **kwargs)

            if response.status_code == 410:
                # Extract current version number from self.api_url
                current_version = int(self.api_url.split("/v")[-1])
                new_version = current_version + 1

                _LOGGER.warning(
                    f"API version v{current_version} is deprecated (410 Gone), "
                    f"automatically switching to v{new_version}"
                )

                # Update API URL to new version
                self.api_url = f"{API_URL}{new_version}"

                # Retry with new version URL
                url = url.replace(f"/v{current_version}", f"/v{new_version}")
                continue

            return response

        raise RuntimeError(f"Failed to find working API version after {max_retries} attempts")

    async def get_profile(self) -> Profile:
        resp = await self._request_with_version_retry(
            "get", f"{self.api_url}?method=profiles.getProfilesByLogin"
        )
        resp.raise_for_status()  # Ensure request was successful
        raw_data_list = resp.json().get("data", {}).get("profiles", [])

        if not raw_data_list:
            raise ValueError("No profile data found in API response")

        # Assume the first profile in the list is the target
        profile_dict = raw_data_list[0]

        # Parse children
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
                        f"Skipping child due to parsing error: {e} - Data: {child_dict}"
                    )

        institution_profile_ids = [
            ip.get("id") for ip in profile_dict.get("institutionProfiles", [])
        ]

        institution_profile_ids.extend([x.id for x in children])

        # Parse main profile
        try:
            profile = Profile(
                _raw=profile_dict,
                profile_id=int(profile_dict.get("profileId")),
                display_name=str(profile_dict.get("displayName", "N/A")),
                children=children,
                institution_profile_ids=institution_profile_ids,
            )
        except (TypeError, ValueError) as e:
            _LOGGER.error(f"Failed to parse main profile: {e} - Data: {profile_dict}")
            raise ValueError("Failed to parse main profile data") from e

        return profile

    async def is_logged_in(self) -> bool:
        """Check if session is still authenticated."""
        if not self._client:
            return False

        try:
            await self.get_profile()
        except Exception as e:
            _LOGGER.debug(f"is_logged_in check failed: {e}")
            return False
        return True

    async def get_profile_context(self) -> ProfileContext:
        resp = await self._request_with_version_retry(
            "get",
            f"{self.api_url}?method=profiles.getProfileContext&portalrole=guardian",
        )
        resp.raise_for_status()
        return ProfileContext(_raw=resp.json())

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
                f"Could not fetch daily overview for child {child_id}: HTTP {resp.status_code}"
            )
            return None
        data = resp.json().get("data")
        if not data:
            _LOGGER.warning(f"No daily overview data for child {child_id}")
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
                    _raw=t_dict,  # Keep passing raw data as well
                )
                threads.append(thread)
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning(
                    f"Skipping message thread due to initialization error: {e} - Data: {t_dict}"
                )
        return threads

    async def get_messages_for_thread(self, thread_id: int, limit: int = 5) -> list[Message]:
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
                        f"Skipping message due to parsing error: {e} - Data: {msg_dict}"
                    )
            # Stop if we have reached the limit
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

        headers = {"content-type": "application/json"}
        if self._client and self._client.cookies:
            csrf_token = self._client.cookies.get("Csrfp-Token")
            if csrf_token:
                headers["csrfp-token"] = csrf_token

        resp = await self._request_with_version_retry(
            "post",
            f"{self.api_url}?method=calendar.getEventsByProfileIdsAndResourceIds",
            headers=headers,
            json=data,
        )

        resp.raise_for_status()
        data = resp.json()

        events = []
        raw_events = data.get("data", [])
        if not isinstance(raw_events, list):
            _LOGGER.warning(f"Unexpected data format for calendar events: {raw_events}")
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
                        teacher_name=teacher.get("teacherName"),
                        has_substitute=has_substitute,
                        substitute_name=substitute.get("teacherName"),
                        location=location,
                        belongs_to=next(iter(event.get("belongsToProfiles")), None),
                        _raw=event,
                    )
                )
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning(
                    f"Skipping calendar event due to initialization error: {e} - Data: {event}"
                )
                raise

        return events

    async def get_posts(
        self,
        institution_profile_ids: list[int],
        page: int = 1,
        limit: int = 10,
    ) -> list[Post]:
        """
        Fetch posts from Aula.

        Args:
            page: Page number to fetch (1-based)
            limit: Number of posts per page
            institution_profile_ids: List of institution profile IDs to filter by

        Returns:
            List of Post objects
        """
        params = {
            "method": "posts.getAllPosts",
            "parent": "profile",
            "index": page - 1,  # API uses 0-based index
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

                _LOGGER.debug("Processing post data: %s", post_data)  # Debug log

                # Check if this is a post object with the expected structure
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

    async def get_mu_tasks(self, widget_id: str, child_filter: list[str], week: str) -> Appointment:
        token = await self._get_bearer_token(widget_id)
        url = f"{MIN_UDDANNELSE_API}/opgaveliste?assuranceLevel=2&childFilter={','.join(child_filter)}&currentWeekNumber={week}&isMobileApp=false&placement=narrow"
        resp = await self._request_with_version_retry("get", url, headers={"Authorization": token})
        data = resp.json()
        appointment = data.get("data", {}).get("appointments", [{}])[0]
        return Appointment(
            _raw=appointment,
            appointment_id=appointment.get("appointmentId"),
            title=appointment.get("title"),
        )

    async def get_ugeplan(self, widget_id: str, child_filter: list[str], week: str) -> Appointment:
        token = await self._get_bearer_token(widget_id)
        url = f"{MIN_UDDANNELSE_API}/ugebrev?assuranceLevel=2&childFilter={','.join(child_filter)}&currentWeekNumber={week}&isMobileApp=false&placement=narrow"
        resp = await self._request_with_version_retry("get", url, headers={"Authorization": token})
        data = resp.json()
        appointment = data.get("data", {}).get("appointments", [{}])[0]
        return Appointment(
            _raw=appointment,
            appointment_id=appointment.get("appointmentId"),
            title=appointment.get("title"),
        )

    async def get_easyiq_weekplan(
        self, week: str, session_uuid: str, institution_filter: list[str], child_id: str
    ) -> Appointment:
        token = await self._get_bearer_token("0001")
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
        data = resp.json()
        appointment = data.get("data", {}).get("appointments", [{}])[0]
        return Appointment(
            _raw=appointment,
            appointment_id=appointment.get("appointmentId"),
            title=appointment.get("title"),
        )

    async def get_huskeliste(self, children: list[str], institutions: list[str]) -> Appointment:
        token = await self._get_bearer_token("0062")
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
        data = resp.json()
        appointment = data.get("data", {}).get("appointments", [{}])[0]
        return Appointment(
            _raw=appointment,
            appointment_id=appointment.get("appointmentId"),
            title=appointment.get("title"),
        )

    async def _get_bearer_token(self, widget_id: str) -> str:
        # reuse or fetch new
        # simplistic: always fetch
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
        """Close HTTP clients and cleanup resources."""
        if self._client:
            await self._client.aclose()
        if self._auth_client:
            await self._auth_client.close()
