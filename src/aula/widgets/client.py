import logging
from typing import Any, Protocol

from ..const import (
    CICERO_API,
    EASYIQ_API,
    EASYIQ_AUTHENTICATE_PATH,
    EASYIQ_CALENDAR_PATH,
    EASYIQ_CHILDREN_PATH,
    EASYIQ_HOMEWORK_PATH,
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
from ..utils.week import monday_of_week

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
        # Whether POST /Aula/AuthenticateAulaUser has run for this client.
        self._easyiq_session_ready = False
        # child UniLogin (casefolded) -> EasyIQ's own ID, from GetChildren.
        self._easyiq_child_ids: dict[str, str] = {}

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

    def easyiq_headers(
        self,
        token: str,
        institution_filter: list[str],
        guardian_login: str,
        child_user_ids: list[str],
        child_user_id: str = "",
    ) -> dict[str, str]:
        """Headers the EasyIQ portal expects from its embedded widgets.

        Mirrors the widget's own ``GetAulaHeaders`` (``/ts/Code/Util.js``).
        ``x-child`` is one child's UniLogin and ``x-childfilter`` is all of
        the guardian's children's UniLogins; both are required on every
        portal call, not just the session bootstrap. A guardian login in
        either is rejected, and omitting them makes ``GetChildren`` answer
        200 with an empty list, which reads as "no children" rather than as
        a malformed request.
        """
        return {
            "Authorization": token,
            "Accept": "application/json",
            "x-institutionfilter": ",".join(institution_filter),
            "x-userprofile": "guardian",
            "x-login": guardian_login,
            "x-child": child_user_id or (child_user_ids[0] if child_user_ids else ""),
            "x-childfilter": ",".join(child_user_ids),
            "x-requested-with": "XMLHttpRequest",
            # EasyIQ only serves these controllers to callers that look like
            # the embedded widget.
            "Referer": f"{EASYIQ_PORTAL}/UgeplanWidget",
        }

    async def ensure_easyiq_session(
        self,
        institution_filter: list[str],
        guardian_login: str,
        child_user_ids: list[str],
    ) -> None:
        """Establish the EasyIQ portal session once, and learn its child IDs.

        ``POST /Aula/AuthenticateAulaUser`` is what the embedded widget does
        before anything else (``/ts/Code/Aula.js``); it sets the session
        cookies the portal's other controllers require. ``GetChildren`` then
        returns EasyIQ's own ``Id`` per child, which is the ``loginId`` those
        controllers expect and which appears nowhere in the Aula API.

        Best-effort: a failure is logged rather than raised, leaving the
        identifier guessing in :meth:`easyiq_identifier_variants` as a
        fallback for institutions this flow does not suit.
        """
        if self._easyiq_session_ready or not child_user_ids:
            return

        token = await self._get_bearer_token(WIDGET_EASYIQ_HOMEWORK)
        headers = self.easyiq_headers(token, institution_filter, guardian_login, child_user_ids)
        try:
            resp = await self._api_client._request_with_version_retry(
                "post", f"{EASYIQ_PORTAL}{EASYIQ_AUTHENTICATE_PATH}", headers=headers
            )
            resp.raise_for_status()
        except Exception as e:
            _LOGGER.info("EasyIQ session bootstrap failed (%s); falling back to guessing", e)
            return

        self._easyiq_session_ready = True

        try:
            resp = await self._api_client._request_with_version_retry(
                "get", f"{EASYIQ_PORTAL}{EASYIQ_CHILDREN_PATH}", headers=headers
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            _LOGGER.info("EasyIQ GetChildren failed (%s); falling back to guessing", e)
            return

        entries = payload.get("Children", []) if isinstance(payload, dict) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            folded = {str(k).lower(): v for k, v in entry.items()}
            # Match on Login, the child's UniLogin, which is the same value
            # Aula calls userId. Names are neither unique nor stable.
            login = str(folded.get("login") or "").casefold()
            easyiq_id = str(folded.get("id") or "")
            if login and easyiq_id:
                self._easyiq_child_ids[login] = easyiq_id

    def resolve_easyiq_child_id(self, child_user_id: str) -> str | None:
        """Return EasyIQ's own ID for a child, once the session has been made."""
        return self._easyiq_child_ids.get(child_user_id.casefold())

    def easyiq_identifier_variants(
        self,
        child_profile_id: str,
        child_user_id: str,
        guardian_login: str,
        easyiq_child_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """Return the ``(loginId, child header)`` pairs to try, best guess first.

        A pair already known to work for this child leads, then EasyIQ's own
        ID for the child when the session bootstrap resolved one, then the
        Aula-derived guesses that are all that is left without it.
        """
        resolved = [(easyiq_child_id, child_user_id)] if easyiq_child_id else []
        return _ordered_unique(
            self._easyiq_identifiers.get(child_user_id, [])
            + resolved
            + [
                (child_profile_id, child_user_id),
                (child_user_id, child_user_id),
                (child_profile_id, child_profile_id),
                (guardian_login, child_user_id),
            ]
        )

    async def _get_easyiq_events(
        self,
        *,
        path: str,
        extra_params: dict[str, str],
        week: str,
        institution_filter: list[str],
        child_profile_id: str,
        child_user_id: str,
        all_child_user_ids: list[str],
        guardian_login: str,
        widget_id: str,
    ) -> list[EasyIQCalendarEvent]:
        """Read one of the EasyIQ portal's week controllers for a child.

        The session bootstrap normally supplies EasyIQ's own ID for this
        child, which is the ``loginId`` these controllers want. When it does
        not, EasyIQ answers either 500 or 200-with-nothing for identifiers it
        does not recognise, so the known Aula-derived combinations are tried
        in turn and the one that returns rows is remembered. A remembered
        combination that stops working costs one wasted request before the
        rest are tried again.
        """
        await self.ensure_easyiq_session(institution_filter, guardian_login, all_child_user_ids)
        token = await self._get_bearer_token(widget_id)
        base_headers = self.easyiq_headers(
            token, institution_filter, guardian_login, all_child_user_ids, child_user_id
        )
        params = {"date": monday_of_week(week), **extra_params}

        first_empty: list[EasyIQCalendarEvent] | None = None
        last_error: Exception | None = None

        for login_id, child_header in self.easyiq_identifier_variants(
            child_profile_id,
            child_user_id,
            guardian_login,
            self.resolve_easyiq_child_id(child_user_id),
        ):
            # x-childfilter stays the full list; only x-child varies per try.
            headers = {**base_headers, "x-child": child_header}
            try:
                resp = await self._api_client._request_with_version_retry(
                    "get",
                    f"{EASYIQ_PORTAL}{path}",
                    params={**params, "loginId": login_id},
                    headers=headers,
                )
                resp.raise_for_status()
            except Exception as e:
                last_error = e
                _LOGGER.debug("EasyIQ %s rejected loginId=%s: %s", path, login_id, e)
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

    async def get_easyiq_calendar_events(
        self,
        *,
        week: str,
        institution_filter: list[str],
        child_profile_id: str,
        child_user_id: str,
        all_child_user_ids: list[str],
        guardian_login: str,
        widget_id: str = WIDGET_EASYIQ_WEEKPLAN,
    ) -> list[EasyIQCalendarEvent]:
        """Fetch a child's EasyIQ week of lessons and calendar entries.

        This controller carries the weekly plan only. Homework has its own,
        see :meth:`get_easyiq_homework_events`.
        """
        return await self._get_easyiq_events(
            path=EASYIQ_CALENDAR_PATH,
            extra_params={
                "activityFilter": "-1",
                "courseFilter": "-1",
                "textFilter": "",
                "ownWeekPlan": "false",
            },
            week=week,
            institution_filter=institution_filter,
            child_profile_id=child_profile_id,
            child_user_id=child_user_id,
            all_child_user_ids=all_child_user_ids,
            guardian_login=guardian_login,
            widget_id=widget_id,
        )

    async def get_easyiq_homework_events(
        self,
        *,
        week: str,
        institution_filter: list[str],
        child_profile_id: str,
        child_user_id: str,
        all_child_user_ids: list[str],
        guardian_login: str,
        widget_id: str = WIDGET_EASYIQ_HOMEWORK,
    ) -> list[EasyIQCalendarEvent]:
        """Fetch a child's EasyIQ homework rows for a week.

        The weekly plan controller never returns homework, so this reads the
        homework widget's own controller. Guardians send an empty
        ``activityFilter``, which is what the widget itself does.
        """
        return await self._get_easyiq_events(
            path=EASYIQ_HOMEWORK_PATH,
            extra_params={"activityFilter": ""},
            week=week,
            institution_filter=institution_filter,
            child_profile_id=child_profile_id,
            child_user_id=child_user_id,
            all_child_user_ids=all_child_user_ids,
            guardian_login=guardian_login,
            widget_id=widget_id,
        )

    async def get_easyiq_weekplan(
        self,
        week: str,
        session_uuid: str,
        institution_filter: list[str],
        child_id: str,
        widget_id: str = WIDGET_EASYIQ_WEEKPLAN,
        *,
        child_profile_id: str | None = None,
        all_child_user_ids: list[str] | None = None,
    ) -> list[Appointment]:
        """Fetch a child's EasyIQ weekly plan.

        Tries the ``weekplaninfo`` API first and falls back to the school
        portal's calendar, which is the only source that still serves some
        institutions. The fallback needs ``child_profile_id`` (the child's
        institution profile ID) to identify the child, so it is skipped when
        the caller cannot supply one. ``all_child_user_ids`` is every child's
        UniLogin, which the portal requires as ``x-childfilter``.
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
            all_child_user_ids=all_child_user_ids or [child_id],
            guardian_login=session_uuid,
            widget_id=widget_id,
        )
        return [
            Appointment(
                _raw=event._raw,
                # The row's own ID: two lessons can start at the same minute.
                appointment_id=event.event_id or event.start,
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
        all_child_user_ids: list[str] | None = None,
    ) -> list[EasyIQHomework]:
        """Fetch a child's EasyIQ homework for a week.

        ``child_id`` is the child's Aula user ID and ``child_profile_id`` their
        institution profile ID; EasyIQ wants both. ``all_child_user_ids`` is
        every child's UniLogin, which the portal requires as ``x-childfilter``.
        """
        events = await self.get_easyiq_homework_events(
            week=week,
            institution_filter=institution_filter,
            child_profile_id=child_profile_id,
            child_user_id=child_id,
            all_child_user_ids=all_child_user_ids or [child_id],
            guardian_login=session_uuid,
        )
        homework = [event for event in events if event.item_type in HOMEWORK_ITEM_TYPES]
        if events and not homework:
            # The controller only serves homework, so an unfamiliar item type
            # is no reason to drop the rows and report nothing.
            _LOGGER.info(
                "EasyIQ homework returned %d row(s) of item type %s, none of type %s; keeping them",
                len(events),
                sorted({event.item_type for event in events}, key=str),
                HOMEWORK_ITEM_TYPES,
            )
            homework = events
        return [EasyIQHomework.from_calendar_event(event) for event in homework]

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
