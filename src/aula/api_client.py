from datetime import datetime
import logging
from typing import Dict, List, Optional
import pytz

import httpx
from bs4 import BeautifulSoup

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

# Logger
_LOGGER = logging.getLogger(__name__)


class AulaApiClient:
    """
    Async client for Aula API endpoints and parsing.
    Based on work of https://github.com/scaarup/aula
    """

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.api_url = f"{API_URL}{API_VERSION}"
        self._client: Optional[httpx.AsyncClient] = None

    async def login(self) -> None:
        """Authenticate and discover latest API URL."""
        self._client = httpx.AsyncClient(follow_redirects=True)
        # 1. Initial login page
        resp = await self._client.get(
            "https://login.aula.dk/auth/login.php",
            params={"type": "unilogin"},
            headers={"User-Agent": USER_AGENT},
        )
        soup = BeautifulSoup(resp.text, "lxml")
        # Ensure login form is present
        form = soup.find("form")
        if not form or not form.has_attr("action"):
            _LOGGER.error(
                "Login form not found (status %s). Response body: %s",
                resp.status_code,
                resp.text[:200],
            )
            raise RuntimeError("Unable to locate login form in Aula login page")

        # 2. Select uni_idp
        resp = await self._client.post(
            form["action"],
            data={"selectedIdp": "uni_idp"},
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        # 3. Credentials
        # follow redirects and 2FA forms
        user_data = {
            "username": self.username,
            "password": self.password,
            "selected-aktoer": "KONTAKT",
        }
        for i in range(10):
            _LOGGER.debug(f"Login redirect loop {i}")

            soup = BeautifulSoup(resp.text, "lxml")
            data = {
                inp["name"]: inp.get("value")
                for inp in soup.find_all("input")
                if inp.has_attr("name")
            }
            data.update(user_data)
            resp = await self._client.post(soup.form["action"], data=data)
            # httpx.Response.url is a URL object; convert to string before checking prefix
            if resp.url == "https://www.aula.dk:443/portal/":
                break

        await self._set_correct_api_version()

    async def _set_correct_api_version(self) -> None:
        api_version = int(API_VERSION)
        while True:
            version_check = await self._client.get(
                f"{self.api_url}?method=profiles.getProfilesByLogin"
            )
            if version_check.status_code == 410:
                api_version += 1
                continue
            if version_check.status_code == 200:
                self.api_url = f"{API_URL}{api_version}"
                break
            version_check.raise_for_status()

    async def get_profile(self) -> Profile:
        resp = await self._client.get(
            f"{self.api_url}?method=profiles.getProfilesByLogin"
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
        resp = await self._client.get(
            f"{self.api_url}?method=profiles.getProfileContext"
        )
        resp.raise_for_status()
        return ProfileContext(_raw=resp.json())

    async def get_daily_overview(self, child_id: int) -> DailyOverview:
        """Fetches the daily overview for a specific child."""
        resp = await self._client.get(
            f"{self.api_url}?method=presence.getDailyOverview&childIds[]={child_id}"
        )
        return DailyOverview.from_dict(resp.json()["data"][0])

    async def get_message_threads(self) -> List[MessageThread]:
        resp = await self._client.get(
            f"{self.api_url}?method=messaging.getThreads&sortOn=date&orderDirection=desc&page=0"
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

    async def get_messages_for_thread(
        self, thread_id: int, limit: int = 5
    ) -> List[Message]:
        """Fetches the latest messages for a specific thread."""
        resp = await self._client.get(
            f"{self.api_url}?method=messaging.getMessagesForThread&threadId={thread_id}&page=0&limit={limit}"
        )
        resp.raise_for_status()
        data = resp.json()
        messages = []
        raw_messages = data.get("data", {}).get("messages", [])

        for msg_dict in raw_messages:
            if msg_dict.get("messageType") == "Message":
                try:
                    text = msg_dict.get("text", {}).get("html") or msg_dict.get(
                        "text", ""
                    )
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
        self, institution_profile_ids: List[int], start: datetime, end: datetime
    ) -> List[CalendarEvent]:

        data = {
            "instProfileIds": institution_profile_ids,
            "resourceIds": [],
            "start": start.strftime("%Y-%m-%d 00:00:00.0000%z"),
            "end": end.strftime("%Y-%m-%d 23:59:59.0000%z"),
        }

        csrf_token = None
        if self._client and self._client.cookies:
            csrf_token = self._client.cookies.get("Csrfp-Token")

        resp = await self._client.post(
            f"{self.api_url}?method=calendar.getEventsByProfileIdsAndResourceIds",
            headers={"content-type": "application/json", "csrfp-token": csrf_token},
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
                lesson = (event.get("lesson", {}) or {})

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
                        belongs_to= next(iter(event.get("belongsToProfiles")), None),
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
        institution_profile_ids: List[int],
        page: int = 1, 
        limit: int = 10, 
    ) -> List[Post]:
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
            "institutionProfileIds[]": institution_profile_ids
        }

        _LOGGER.debug("Fetching posts with params: %s", params)
        
        resp = await self._client.get(
            self.api_url,
            params=params
        )

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
                    _LOGGER.warning("Skipping invalid post data (missing required fields): %s", post_data)
            except (TypeError, ValueError, KeyError) as e:
                _LOGGER.warning(
                    "Skipping post due to parsing error: %s - Data: %s",
                    e,
                    post_data,
                    exc_info=_LOGGER.isEnabledFor(logging.DEBUG)
                )
                continue
                
        return posts

    async def get_mu_tasks(
        self, widget_id: str, child_filter: List[str], week: str
    ) -> Appointment:
        token = await self._get_bearer_token(widget_id)
        url = f"{MIN_UDDANNELSE_API}/opgaveliste?assuranceLevel=2&childFilter={','.join(child_filter)}&currentWeekNumber={week}&isMobileApp=false&placement=narrow"
        resp = await self._client.get(url, headers={"Authorization": token})
        data = resp.json()
        appointment = data.get("data", {}).get("appointments", [{}])[0]
        return Appointment(
            _raw=appointment,
            appointment_id=appointment.get("appointmentId"),
            title=appointment.get("title"),
        )

    async def get_ugeplan(
        self, widget_id: str, child_filter: List[str], week: str
    ) -> Appointment:
        token = await self._get_bearer_token(widget_id)
        url = f"{MIN_UDDANNELSE_API}/ugebrev?assuranceLevel=2&childFilter={','.join(child_filter)}&currentWeekNumber={week}&isMobileApp=false&placement=narrow"
        resp = await self._client.get(url, headers={"Authorization": token})
        data = resp.json()
        appointment = data.get("data", {}).get("appointments", [{}])[0]
        return Appointment(
            _raw=appointment,
            appointment_id=appointment.get("appointmentId"),
            title=appointment.get("title"),
        )

    async def get_easyiq_weekplan(
        self, week: str, session_uuid: str, institution_filter: List[str], child_id: str
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
        resp = await self._client.post(
            f"{EASYIQ_API}/weekplaninfo", json=payload, headers=headers
        )
        data = resp.json()
        appointment = data.get("data", {}).get("appointments", [{}])[0]
        return Appointment(
            _raw=appointment,
            appointment_id=appointment.get("appointmentId"),
            title=appointment.get("title"),
        )

    async def get_huskeliste(
        self, children: List[str], institutions: List[str]
    ) -> Appointment:
        token = await self._get_bearer_token("0062")
        params = {
            "children": ",".join(children),
            "institutions": ",".join(institutions),
        }
        resp = await self._client.get(
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
        resp = await self._client.get(
            f"{self.api_url}?method=aulaToken.getAulaToken&widgetId={widget_id}"
        )
        token = "Bearer " + str(resp.json()["data"])
        return token

    def _parse_date(self, date_str: str) -> datetime:
        return datetime.fromisoformat(date_str).astimezone(pytz.timezone("CET"))

    def _find_participant_by_role(self, lesson: Dict, role: str):
        participants = lesson.get("participants", [])

        return next(
            (x for x in participants if x.get("participantRole") == role),
            {},
        )