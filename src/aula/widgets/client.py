import datetime
import logging
from typing import Any, Protocol

from ..const import (
    CICERO_API,
    EASYIQ_API,
    EASYIQ_PORTAL,
    MEEBOOK_API,
    MIN_UDDANNELSE_API,
    SYSTEMATIC_API,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_EASYIQ_WEEKPLAN,
    WIDGET_HUSKELISTEN,
    WIDGET_MEEBOOK,
)
from ..http import HttpResponse
from ..models import (
    HOMEWORK_ITEM_TYPES,
    WEEKPLAN_ITEM_TYPES,
    Appointment,
    EasyIQCalendarEvent,
    EasyIQHomework,
    LibraryStatus,
    MeebookStudentPlan,
    MomoUserCourses,
    MUTask,
    MUWeeklyPerson,
    UserReminders,
)

_LOGGER = logging.getLogger(__name__)


def _as_list(data: Any, provider: str) -> list[Any]:
    """Return ``data`` if it is a list of dicts, else log and return an empty list.

    Widget providers sometimes answer 2xx with an error object instead of the
    documented array, e.g. Meebook's ``{"message": "JWT-Token expired, please
    renew."}``. Iterating that yields the keys as strings, which blows up in
    ``from_dict``. ``data`` is also ``None`` when the body was not valid JSON.
    """
    if not isinstance(data, list):
        _LOGGER.warning(
            "%s returned %s instead of a list, treating as empty: %s",
            provider,
            type(data).__name__,
            data,
        )
        return []

    items = [item for item in data if isinstance(item, dict)]
    if len(items) != len(data):
        _LOGGER.warning(
            "%s returned %d non-dict item(s), skipping them",
            provider,
            len(data) - len(items),
        )
    return items


def _monday_of_week(week: str) -> str:
    """Return the Monday of ``YYYY-Wnn`` as the timestamp EasyIQ's portal wants.

    The portal takes a single ``date`` and answers with the week containing it,
    so any day in the week would do; Monday keeps it unambiguous. Falls back to
    today when ``week`` cannot be parsed, which is better than sending nothing.
    """
    try:
        year_part, week_part = week.split("-W")
        monday = datetime.date.fromisocalendar(int(year_part), int(week_part), 1)
    except ValueError, AttributeError:
        _LOGGER.warning("Could not parse week %r, using today's date instead", week)
        monday = datetime.date.today()
    return f"{monday.isoformat()}T00:00:00Z"


def _ordered_unique(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop repeats while keeping first-seen order."""
    seen: set[tuple[str, str]] = set()
    unique = []
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique


def _extract_events(payload: Any) -> list[dict[str, Any]]:
    """Pull the event list out of EasyIQ's calendar response.

    The portal has answered with both a bare array and an object wrapping one,
    so both shapes are unwrapped rather than assumed.
    """
    if isinstance(payload, list):
        return [event for event in payload if isinstance(event, dict)]
    if isinstance(payload, dict):
        for key in ("events", "calendarEvents", "items", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [event for event in value if isinstance(event, dict)]
            if isinstance(value, dict):
                nested = _extract_events(value)
                if nested:
                    return nested
    return []


class _WidgetRequestClient(Protocol):
    api_url: str

    async def _request_with_version_retry(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: object | None = None,
    ) -> HttpResponse: ...


class AulaWidgetsClient:
    """Widget provider API client for third-party Aula integrations."""

    def __init__(self, api_client: _WidgetRequestClient) -> None:
        self._api_client = api_client
        # child user ID -> the (loginId, child header) pair EasyIQ accepted.
        self._easyiq_identifiers: dict[str, list[tuple[str, str]]] = {}

    async def _get_bearer_token(self, widget_id: str) -> str:
        resp = await self._api_client._request_with_version_retry(
            "get",
            f"{self._api_client.api_url}?method=aulaToken.getAulaToken&widgetId={widget_id}",
        )
        resp.raise_for_status()
        token = "Bearer " + str(resp.json()["data"])
        return token

    async def get_mu_tasks(
        self,
        widget_id: str,
        child_filter: list[str],
        institution_filter: list[str],
        week: str,
        session_uuid: str,
    ) -> list[MUTask]:
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

        resp = await self._api_client._request_with_version_retry(
            "get",
            f"{MIN_UDDANNELSE_API}/opgaveliste",
            params=params,
            headers={"Authorization": token, "Accept": "application/json"},
        )
        resp.raise_for_status()
        return [MUTask.from_dict(o) for o in resp.json().get("opgaver", [])]

    async def get_ugeplan(
        self,
        widget_id: str,
        child_filter: list[str],
        institution_filter: list[str],
        week: str,
        session_uuid: str,
    ) -> list[MUWeeklyPerson]:
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

        resp = await self._api_client._request_with_version_retry(
            "get",
            f"{MIN_UDDANNELSE_API}/ugebrev",
            params=params,
            headers={"Authorization": token, "Accept": "application/json"},
        )
        resp.raise_for_status()
        return [MUWeeklyPerson.from_dict(p) for p in resp.json().get("personer", [])]

    async def get_easyiq_calendar_events(
        self,
        *,
        week: str,
        institution_filter: list[str],
        child_profile_id: str,
        child_user_id: str,
        guardian_login: str,
        widget_id: str = WIDGET_EASYIQ_WEEKPLAN,
    ) -> list[EasyIQCalendarEvent]:
        """Fetch a child's whole EasyIQ week from the school portal.

        One request returns lessons, calendar entries and homework together;
        callers split them on ``item_type``.

        EasyIQ accepts different Aula identifiers for ``loginId`` and the child
        headers depending on the institution, and answers 200-with-nothing for
        the combinations it does not recognise. Rather than guess, this tries
        the known combinations in turn and keeps the one that returns rows,
        remembering it so later weeks cost a single request. A remembered
        combination that stops working just costs one wasted request before
        the rest are tried again.
        """
        token = await self._get_bearer_token(widget_id)
        base_headers = {
            "Authorization": token,
            "Accept": "application/json",
            "x-institutionfilter": ",".join(institution_filter),
            "x-userprofile": "guardian",
            "x-login": guardian_login,
            "x-requested-with": "XMLHttpRequest",
            # EasyIQ only serves the calendar to callers that look like the
            # embedded widget.
            "Referer": f"{EASYIQ_PORTAL}/UgeplanWidget",
        }
        params = {
            "date": _monday_of_week(week),
            "activityFilter": "-1",
            "courseFilter": "-1",
            "textFilter": "",
            "ownWeekPlan": "false",
        }

        variants = _ordered_unique(
            self._easyiq_identifiers.get(child_user_id, [])
            + [
                (child_profile_id, child_user_id),
                (child_user_id, child_user_id),
                (child_profile_id, child_profile_id),
                (guardian_login, child_user_id),
            ]
        )

        first_empty: list[EasyIQCalendarEvent] | None = None
        last_error: Exception | None = None

        for login_id, child_header in variants:
            headers = {**base_headers, "x-child": child_header, "x-childfilter": child_header}
            try:
                resp = await self._api_client._request_with_version_retry(
                    "get",
                    f"{EASYIQ_PORTAL}/Calendar/CalendarGetWeekplanEvents",
                    params={**params, "loginId": login_id},
                    headers=headers,
                )
                resp.raise_for_status()
            except Exception as e:
                last_error = e
                _LOGGER.debug("EasyIQ calendar rejected loginId=%s: %s", login_id, e)
                continue

            events = [EasyIQCalendarEvent.from_dict(e) for e in _extract_events(resp.json())]
            if events:
                self._easyiq_identifiers[child_user_id] = [(login_id, child_header)]
                return events
            if first_empty is None:
                first_empty = events

        if first_empty is not None:
            return first_empty
        if last_error is not None:
            raise last_error
        return []

    async def get_easyiq_weekplan(
        self,
        week: str,
        session_uuid: str,
        institution_filter: list[str],
        child_id: str,
        widget_id: str = WIDGET_EASYIQ_WEEKPLAN,
        *,
        child_profile_id: str | None = None,
    ) -> list[Appointment]:
        """Fetch a child's EasyIQ weekly plan.

        Tries the ``weekplaninfo`` API first and falls back to the school
        portal's calendar, which is the only source that still serves some
        institutions. The fallback needs ``child_profile_id`` (the child's
        institution profile ID) to identify the child, so it is skipped when
        the caller cannot supply one.
        """
        token = await self._get_bearer_token(widget_id)
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
        appointments: list[dict[str, Any]] = []
        try:
            resp = await self._api_client._request_with_version_retry(
                "post", f"{EASYIQ_API}/weekplaninfo", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            envelope = data.get("data") if isinstance(data, dict) else None
            if isinstance(envelope, dict):
                appointments = _as_list(envelope.get("appointments", []), "EasyIQ weekplan")
        except Exception as e:
            if child_profile_id is None:
                raise
            _LOGGER.info("EasyIQ weekplaninfo failed (%s), falling back to the portal", e)

        if appointments:
            return [Appointment.from_dict(a) for a in appointments]
        if child_profile_id is None:
            return []

        events = await self.get_easyiq_calendar_events(
            week=week,
            institution_filter=institution_filter,
            child_profile_id=child_profile_id,
            child_user_id=child_id,
            guardian_login=session_uuid,
            widget_id=widget_id,
        )
        return [
            Appointment(
                _raw=event._raw,
                appointment_id=event.start,
                title=event.title,
                start=event.start,
                end=event.end,
                description=event.description,
                item_type=event.item_type,
            )
            for event in events
            if event.item_type in WEEKPLAN_ITEM_TYPES
        ]

    async def get_easyiq_homework(
        self,
        week: str,
        session_uuid: str,
        institution_filter: list[str],
        child_id: str,
        *,
        child_profile_id: str,
    ) -> list[EasyIQHomework]:
        """Fetch a child's EasyIQ homework for a week.

        ``child_id`` is the child's Aula user ID and ``child_profile_id`` their
        institution profile ID; EasyIQ wants both.
        """
        events = await self.get_easyiq_calendar_events(
            week=week,
            institution_filter=institution_filter,
            child_profile_id=child_profile_id,
            child_user_id=child_id,
            guardian_login=session_uuid,
            widget_id=WIDGET_EASYIQ_HOMEWORK,
        )
        return [
            EasyIQHomework.from_calendar_event(event)
            for event in events
            if event.item_type in HOMEWORK_ITEM_TYPES
        ]

    async def get_meebook_weekplan(
        self,
        child_filter: list[str],
        institution_filter: list[str],
        week: str,
        session_uuid: str,
    ) -> list[MeebookStudentPlan]:
        token = await self._get_bearer_token(WIDGET_MEEBOOK)

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

        resp = await self._api_client._request_with_version_retry(
            "get",
            f"{MEEBOOK_API}/relatedweekplan/all",
            params=params,
            headers=headers,
        )
        resp.raise_for_status()
        plans = _as_list(resp.json(), "Meebook weekplan")
        return [MeebookStudentPlan.from_dict(s) for s in plans]

    async def get_momo_courses(
        self,
        children: list[str],
        institutions: list[str],
        session_uuid: str,
    ) -> list[MomoUserCourses]:
        token = await self._get_bearer_token(WIDGET_HUSKELISTEN)

        params = {
            "widgetVersion": "1.3",
            "userProfile": "guardian",
            "sessionId": session_uuid,
            "children": children,
            "institutions": institutions,
        }

        resp = await self._api_client._request_with_version_retry(
            "get",
            f"{SYSTEMATIC_API}/courses/v1",
            params=params,
            headers={"Aula-Authorization": token},
        )
        resp.raise_for_status()
        courses = _as_list(resp.json(), "Huskelisten courses")
        return [MomoUserCourses.from_dict(u) for u in courses]

    async def get_momo_reminders(
        self,
        children: list[str],
        institutions: list[str],
        session_uuid: str,
        from_date: str,
        due_no_later_than: str,
    ) -> list[UserReminders]:
        token = await self._get_bearer_token(WIDGET_HUSKELISTEN)

        params = {
            "widgetVersion": "1.10",
            "userProfile": "guardian",
            "sessionId": session_uuid,
            "children": children,
            "institutions": institutions,
            "from": from_date,
            "dueNoLaterThan": due_no_later_than,
        }

        resp = await self._api_client._request_with_version_retry(
            "get",
            f"{SYSTEMATIC_API}/reminders/v1",
            params=params,
            headers={"Aula-Authorization": token},
        )
        resp.raise_for_status()
        reminders = _as_list(resp.json(), "Huskelisten reminders")
        return [UserReminders.from_dict(u) for u in reminders]

    async def get_library_status(
        self,
        widget_id: str,
        children: list[str],
        institutions: list[str],
        session_uuid: str,
    ) -> LibraryStatus:
        token = await self._get_bearer_token(widget_id)
        params = {
            "coverImageHeight": "160",
            "widgetVersion": "1.6",
            "userProfile": "guardian",
            "sessionUUID": session_uuid,
            "institutions": institutions,
            "children": children,
        }

        resp = await self._api_client._request_with_version_retry(
            "get",
            f"{CICERO_API}/library/status/v3",
            params=params,
            headers={"Authorization": token, "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            _LOGGER.warning(
                "Library status returned %s instead of an object, treating as empty: %s",
                type(data).__name__,
                data,
            )
            return LibraryStatus()
        return LibraryStatus.from_dict(data)
