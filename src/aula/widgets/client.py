import asyncio
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
    EASYIQ_SWITCHCHILD_PATH,
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


class EasyIQWrongChildSession(Exception):
    """The portal session is on a different child than the one asked for.

    ``AuthenticateAulaUser`` echoes back ``child``, the child the session is
    currently on. When that disagrees with the child we switched to, the read
    that follows would return someone else's week, which is the failure this
    whole flow exists to prevent (issue #68). Two other Aula clients guess
    identifiers and treat "200 and parseable" as success, which is how that
    goes unnoticed; this refuses instead.
    """


class EasyIQChildNotInPortal(Exception):
    """EasyIQ's portal has no identity for this child, so it has no plan.

    ``GetChildren`` lists the children the portal knows. A child missing
    from it is not an error to retry: their institution is not on EasyIQ at
    all -- daycare, typically, which has no week plan. Reading anyway does
    not fail, it returns whichever child the session was last switched to
    (issue #68), so this is raised instead and callers report it as the
    absence it is.
    """


# Enough of an unreadable body to identify it, not enough to fill a log file.
_BODY_LOG_LIMIT = 300


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


def _find_events(payload: Any) -> list[dict[str, Any]] | None:
    """Pull the event list out of EasyIQ's calendar response.

    The portal has answered with both a bare array and an object wrapping one,
    so both shapes are unwrapped rather than assumed. ``None`` means neither
    was there, which is how an error answer arrives: 2xx, a body, no events
    anywhere in it. An empty list is a real answer and stays distinct from it.
    """
    if isinstance(payload, list):
        return [event for event in payload if isinstance(event, dict)]
    if isinstance(payload, dict):
        for key in ("events", "calendarEvents", "items", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [event for event in value if isinstance(event, dict)]
            if isinstance(value, dict):
                nested = _find_events(value)
                if nested:
                    return nested
    return None


def _log_unreadable_body(source: str, payload: Any, **context: str) -> None:
    """Warn about a 2xx body carrying nothing we recognise.

    EasyIQ answers this way when a school is not licensed for a widget, and the
    body is the only place the reason appears. Without a warning it is
    indistinguishable from a genuinely empty week, which has cost people hours.
    The envelope is undocumented and differs between EasyIQ's two backends, so
    the keys and a truncated body are logged rather than named fields.
    """
    body = repr(payload)
    if len(body) > _BODY_LOG_LIMIT:
        body = body[:_BODY_LOG_LIMIT] + "..."

    _LOGGER.warning(
        "%s returned no readable data (%s): keys=%s body=%s",
        source,
        ", ".join(f"{name}={value}" for name, value in context.items()),
        sorted(payload) if isinstance(payload, dict) else None,
        body,
    )


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
        # Serialises the bootstrap so concurrent week reads make it once.
        self._easyiq_session_lock = asyncio.Lock()
        # child UniLogin (casefolded) -> EasyIQ's own ID, from GetChildren.
        self._easyiq_child_ids: dict[str, str] = {}
        # child UniLogin (casefolded) -> the real ``Login`` string
        # GetChildren returned for them. Not always equal in casing to the
        # UniLogin Aula hands us as ``userId``.
        self._easyiq_child_logins: dict[str, str] = {}
        # The parent's loginId from AuthenticateAulaUser. The real client
        # stores this once and reuses it, unchanged, for every child.
        self._easyiq_parent_login_id: str | None = None
        # Whether GetChildren answered with at least one usable entry. Once
        # it has, the mapping above is authoritative: a child absent from it
        # has no EasyIQ identity at all.
        self._easyiq_children_known = False
        # SwitchChild changes server-side session state, so a switch and the
        # read it selects for have to stay together. Without this, two
        # children read concurrently would interleave and each could be
        # answered with the other's data.
        self._easyiq_child_lock = asyncio.Lock()

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

        Safe to await concurrently: callers reading several weeks or children
        at once share the one bootstrap rather than each making their own.
        """
        if self._easyiq_session_ready or not child_user_ids:
            return

        async with self._easyiq_session_lock:
            # Another caller may have finished the bootstrap while this one
            # waited for the lock. Re-check rather than repeat it.
            if self._easyiq_session_ready:
                return
            await self._bootstrap_easyiq_session(institution_filter, guardian_login, child_user_ids)

    async def authenticate_easyiq_session(
        self,
        institution_filter: list[str],
        guardian_login: str,
        child_user_ids: list[str],
        child_user_id: str = "",
        token: str | None = None,
    ) -> dict[str, Any]:
        """``POST /Aula/AuthenticateAulaUser``, returning its body key-folded.

        The portal answers ``{loginId, loginTypeId, child, childName,
        schoolName, schoolId}``. ``child`` is the child the session is
        currently on: the portal stores it as ``SessionStorage.AulaChild``
        and sends it back as ``x-child``. That makes this the one call that
        can say whether a ``SwitchChild`` actually took effect.

        A body that cannot be read comes back as an empty dict rather than
        raising, since every caller can carry on without it. Transport
        failures do raise.
        """
        token = token or await self._get_bearer_token(WIDGET_EASYIQ_HOMEWORK)
        headers = self.easyiq_headers(
            token, institution_filter, guardian_login, child_user_ids, child_user_id
        )
        resp = await self._api_client._request_with_version_retry(
            "post", f"{EASYIQ_PORTAL}{EASYIQ_AUTHENTICATE_PATH}", headers=headers
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception as e:
            _LOGGER.warning("EasyIQ AuthenticateAulaUser body could not be parsed: %s", e)
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key).lower(): value for key, value in payload.items()}

    async def _bootstrap_easyiq_session(
        self,
        institution_filter: list[str],
        guardian_login: str,
        child_user_ids: list[str],
    ) -> None:
        """Make the portal session and read its child IDs. Holds the lock."""
        token = await self._get_bearer_token(WIDGET_EASYIQ_HOMEWORK)
        headers = self.easyiq_headers(token, institution_filter, guardian_login, child_user_ids)
        try:
            body = await self.authenticate_easyiq_session(
                institution_filter, guardian_login, child_user_ids, token=token
            )
        except Exception as e:
            _LOGGER.info("EasyIQ session bootstrap failed (%s); falling back to guessing", e)
            return

        self._easyiq_session_ready = True
        login_id = body.get("loginid")
        if login_id not in (None, ""):
            # The parent's loginId. The real client stores it once and reuses
            # it, unchanged, for every child (issue #68).
            self._easyiq_parent_login_id = str(login_id)

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
            login = str(folded.get("login") or "")
            easyiq_id = str(folded.get("id") or "")
            if login and easyiq_id:
                key = login.casefold()
                self._easyiq_child_ids[key] = easyiq_id
                # Kept in its original casing: it is what the portal expects
                # back as ``x-child``, unlike the lookup key.
                self._easyiq_child_logins[key] = login
                self._easyiq_children_known = True

    def resolve_easyiq_child_id(self, child_user_id: str) -> str | None:
        """Return EasyIQ's own ID for a child, once the session has been made."""
        return self._easyiq_child_ids.get(child_user_id.casefold())

    def resolve_easyiq_child_login(self, child_user_id: str) -> str | None:
        """Return EasyIQ's own ``Login`` string for a child, once resolved.

        This is the exact value the real client sends back as ``x-child``.
        It is the same UniLogin Aula calls ``userId``, but not guaranteed to
        be identical in casing, so it is kept separately rather than assumed.
        """
        return self._easyiq_child_logins.get(child_user_id.casefold())

    def easyiq_identifier_variants(
        self,
        child_profile_id: str,
        child_user_id: str,
        guardian_login: str,
        easyiq_child_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """Return the ``(loginId, child header)`` pairs to try, best guess first.

        The protocol-correct pair leads when both halves of it are known: the
        parent's ``loginId`` from ``AuthenticateAulaUser``, which the real
        client reuses unchanged for every child, paired with this child's
        real ``Login`` string from ``GetChildren``. That is what the real
        client actually sends (issue #68); everything else here is a guess
        that happened to work for some institution.

        When either half is missing, the fallback order is exactly what it
        always was: a pair already known to work for this child, then
        EasyIQ's own ID for the child when the session bootstrap resolved
        one, then the Aula-derived guesses that are all that is left
        without it.
        """
        protocol_correct: list[tuple[str, str]] = []
        real_login = self.resolve_easyiq_child_login(child_user_id)
        if self._easyiq_parent_login_id and real_login:
            protocol_correct = [(self._easyiq_parent_login_id, real_login)]

        resolved = [(easyiq_child_id, child_user_id)] if easyiq_child_id else []
        return _ordered_unique(
            protocol_correct
            + self._easyiq_identifiers.get(child_user_id, [])
            + resolved
            + [
                (child_profile_id, child_user_id),
                (child_user_id, child_user_id),
                (child_profile_id, child_profile_id),
                (guardian_login, child_user_id),
            ]
        )

    async def switch_easyiq_child(
        self,
        child_easyiq_id: str,
        institution_filter: list[str],
        guardian_login: str,
        child_user_ids: list[str],
        child_user_id: str = "",
        token: str | None = None,
    ) -> None:
        """``POST /Aula/SwitchChild``, the portal's own child-selection call.

        The real client always calls this before reading a child's data, and
        follows it with a full page reload; ``x-child`` there is only ever
        written at ``SwitchChild`` time, so it always agrees with the
        server's session state.

        That sequencing turns out to be required. Identity headers alone
        change nothing: four reads carrying four distinct, correct
        ``x-child`` values were all answered with the same child's week
        (issue #68). The child the portal answers for is session state, and
        this call is the only thing that moves it.

        ``child_easyiq_id`` must be the child's ``Id`` from ``GetChildren``
        (:meth:`resolve_easyiq_child_id`) -- not their ``Login`` string, and
        not Aula's own user ID. Pass ``token`` to reuse a bearer token the
        caller already holds rather than fetching a second one.
        """
        token = token or await self._get_bearer_token(WIDGET_EASYIQ_HOMEWORK)
        headers = self.easyiq_headers(
            token, institution_filter, guardian_login, child_user_ids, child_user_id
        )
        resp = await self._api_client._request_with_version_retry(
            "post",
            f"{EASYIQ_PORTAL}{EASYIQ_SWITCHCHILD_PATH}",
            params={"loginId": child_easyiq_id},
            headers=headers,
        )
        resp.raise_for_status()

    async def confirm_easyiq_session_child(
        self,
        expected_child_login: str,
        institution_filter: list[str],
        guardian_login: str,
        child_user_ids: list[str],
        child_user_id: str,
        token: str | None = None,
    ) -> str:
        """Check the portal session really is on the child we asked for.

        Returns the ``child`` value the portal reported, or "" when it
        reported none. Raises :class:`EasyIQWrongChildSession` when it names
        a different child, because the read that would follow returns that
        child's week and nothing downstream could tell.

        Silence is not treated as disagreement: institutions whose answer
        omits ``child`` leave us no worse off than before this check existed.
        """
        body = await self.authenticate_easyiq_session(
            institution_filter, guardian_login, child_user_ids, child_user_id, token
        )
        actual = str(body.get("child") or "")
        if not actual:
            _LOGGER.info(
                "EasyIQ did not report which child the session is on; "
                "the switch could not be confirmed"
            )
            return ""
        if expected_child_login and actual.casefold() != expected_child_login.casefold():
            # Deliberately value-free: this reaches the CLI, and both sides
            # of the comparison are UniLogins.
            raise EasyIQWrongChildSession(
                "EasyIQ's session is on a different child than the one requested"
            )
        return actual

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
        all_institution_filter: list[str] | None = None,
    ) -> list[EasyIQCalendarEvent]:
        """Read one of the EasyIQ portal's week controllers for a child.

        Which child the portal answers for is server-side session state, so
        every read is preceded by ``SwitchChild`` and the two are held
        together under a lock. Skipping the switch does not merely risk
        stale data, it reliably returns the wrong child's week (issue #68).
        The switch is then confirmed against what ``AuthenticateAulaUser``
        says the session is on, so a switch that answered 200 without taking
        effect surfaces as an error instead of as another child's week.

        A child the session bootstrap resolved no EasyIQ ID for is not read
        at all. Those children genuinely have no week plan -- daycare has no
        EasyIQ identity -- and reading anyway does not produce an error, it
        produces whichever child the session last switched to, which looks
        like valid data.

        Only when the bootstrap failed outright, leaving no children known,
        does this fall back to the old behaviour of trying the known
        Aula-derived identifier combinations in turn and remembering the one
        that returns rows. That path cannot select a child and is kept only
        so single-child institutions the bootstrap does not suit keep working.
        """
        # The session is made once per client and its child list is cached, so
        # it has to be established under every institution the guardian has,
        # not just this child's. Bootstrapping under one child's institution
        # would let the first child read decide which children are ever
        # resolvable, and children at the guardian's other institutions could
        # then be mistaken for children EasyIQ does not know.
        await self.ensure_easyiq_session(
            all_institution_filter or institution_filter, guardian_login, all_child_user_ids
        )

        easyiq_child_id = self.resolve_easyiq_child_id(child_user_id)
        if easyiq_child_id is None and self._easyiq_children_known:
            raise EasyIQChildNotInPortal(f"EasyIQ's portal lists no child matching {child_user_id}")

        token = await self._get_bearer_token(widget_id)

        async with self._easyiq_child_lock:
            if easyiq_child_id is not None:
                await self.switch_easyiq_child(
                    easyiq_child_id,
                    institution_filter,
                    guardian_login,
                    all_child_user_ids,
                    child_user_id,
                    token=token,
                )
                # SwitchChild answering 200 is not proof it moved the session.
                # Confirm before reading, so a wrong child is an error rather
                # than plausible-looking data.
                await self.confirm_easyiq_session_child(
                    self.resolve_easyiq_child_login(child_user_id) or "",
                    institution_filter,
                    guardian_login,
                    all_child_user_ids,
                    child_user_id,
                    token,
                )
            return await self._read_easyiq_week(
                path=path,
                extra_params=extra_params,
                week=week,
                institution_filter=institution_filter,
                child_profile_id=child_profile_id,
                child_user_id=child_user_id,
                all_child_user_ids=all_child_user_ids,
                guardian_login=guardian_login,
                widget_id=widget_id,
                easyiq_child_id=easyiq_child_id,
                token=token,
            )

    async def _read_easyiq_week(
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
        easyiq_child_id: str | None,
        token: str,
    ) -> list[EasyIQCalendarEvent]:
        """Issue the week read itself, for the child the session is on.

        Called with :attr:`_easyiq_child_lock` held and the switch already
        done, so the session is pointing at ``child_user_id``. EasyIQ answers
        either 500 or 200-with-nothing for identifiers it does not recognise,
        so the candidate ``(loginId, x-child)`` pairs are tried in turn and
        the one that returns rows is remembered. A remembered pair that stops
        working costs one wasted request before the rest are tried again.
        """
        base_headers = self.easyiq_headers(
            token, institution_filter, guardian_login, all_child_user_ids, child_user_id
        )
        params = {"date": monday_of_week(week), **extra_params}

        first_empty: list[EasyIQCalendarEvent] | None = None
        last_error: Exception | None = None
        unreadable: list[Any] = []

        for login_id, child_header in self.easyiq_identifier_variants(
            child_profile_id,
            child_user_id,
            guardian_login,
            easyiq_child_id,
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

            payload = resp.json()
            found = _find_events(payload)
            if found is None:
                # Nothing readable in this answer; the next identifier may fare
                # better, so keep the body for the warning and carry on.
                unreadable.append(payload)
                continue

            events = [EasyIQCalendarEvent.from_dict(e) for e in found]
            if events:
                self._easyiq_identifiers[child_user_id] = [(login_id, child_header)]
                return events
            if first_empty is None:
                first_empty = events

        if unreadable:
            _log_unreadable_body(
                f"EasyIQ {path}",
                unreadable[0],
                widget=widget_id,
                child=child_user_id,
                week=week,
            )

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
        all_institution_filter: list[str] | None = None,
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
            all_institution_filter=all_institution_filter,
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
        all_institution_filter: list[str] | None = None,
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
            all_institution_filter=all_institution_filter,
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
        all_institution_filter: list[str] | None = None,
    ) -> list[Appointment]:
        """Fetch a child's EasyIQ weekly plan.

        Tries the ``weekplaninfo`` API first and falls back to the school
        portal's calendar, which is the only source that still serves some
        institutions. The fallback needs ``child_profile_id`` (the child's
        institution profile ID) to identify the child, so it is skipped when
        the caller cannot supply one. ``all_child_user_ids`` is every child's
        UniLogin, which the portal requires as ``x-childfilter``, and
        ``all_institution_filter`` every institution the guardian has, which
        is what the portal session is established under.

        Raises :class:`EasyIQChildNotInPortal` when the portal knows no such
        child, which means they have no week plan rather than that anything
        went wrong.
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
            elif not (isinstance(data, dict) and "data" in data):
                # An explicit null under "data" is the API saying it has none.
                # Anything else means we are reading a shape we do not know.
                _log_unreadable_body(
                    "EasyIQ weekplaninfo", data, widget=widget_id, child=child_id, week=week
                )
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
            all_institution_filter=all_institution_filter,
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
                activities=event.activities,
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
        all_institution_filter: list[str] | None = None,
    ) -> list[EasyIQHomework]:
        """Fetch a child's EasyIQ homework for a week.

        ``child_id`` is the child's Aula user ID and ``child_profile_id`` their
        institution profile ID; EasyIQ wants both. ``all_child_user_ids`` is
        every child's UniLogin, which the portal requires as ``x-childfilter``,
        and ``all_institution_filter`` every institution the guardian has,
        which is what the portal session is established under.

        Raises :class:`EasyIQChildNotInPortal` when the portal knows no such
        child, which means they have no homework rather than that anything
        went wrong.
        """
        events = await self.get_easyiq_homework_events(
            week=week,
            institution_filter=institution_filter,
            child_profile_id=child_profile_id,
            child_user_id=child_id,
            all_child_user_ids=all_child_user_ids or [child_id],
            guardian_login=session_uuid,
            all_institution_filter=all_institution_filter,
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
