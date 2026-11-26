from collections.abc import Iterable, Sequence
from zoneinfo import ZoneInfo

from ..api_client import AulaApiClient
from ..models import (
    Child,
    DocendoWeekPlan,
    MessageThread,
    Profile,
)
from ..utils.dates import aula_today
from ..utils.diagnostics import credential_logger
from ..utils.mapping import get_in
from ..utils.output import (
    print_error,
)
from ..utils.week import DANISH_WEEKDAYS
from ..widgets import WidgetContext

_LOGGER = credential_logger(__name__)


def _resolve_week(week: str | None) -> str:
    """Resolve a week argument to YYYY-Wn format.

    Accepts None (current week), a bare number like '8', or full 'YYYY-Wn'.
    """
    today = aula_today().isocalendar()
    if week is None:
        return f"{today.year}-W{today.week}"
    if week.isdigit():
        return f"{today.year}-W{int(week)}"
    return week


def _unique_names(name_lists: Iterable[list[str]]) -> list[str]:
    """Flatten per-event name lists into one de-duplicated, ordered list."""
    return list(dict.fromkeys(name for names in name_lists for name in names if name))


#: Widget IDs already looked up, per client, so weekly-summary's five
#: providers cost one request rather than five. ``None`` records a lookup
#: that failed, which must not be retried on every provider either.
_WIDGET_ID_CACHE: dict[int, set[str] | None] = {}


async def _has_widget(client: AulaApiClient, widget_id: str) -> bool:
    """Whether this account has ``widget_id`` on its Aula dashboard.

    Aula issues a widget token whether or not the account has the widget, so
    a command that skips this check reaches the supplier with a token the
    supplier will not honour, and the user sees the supplier's error (a bare
    401 or 400) instead of being told the widget is missing.

    A lookup that fails does not block: better to attempt the call and show
    whatever comes back than to refuse on incomplete information.
    """
    available = await _available_widget_ids(client)
    return True if available is None else widget_id in available


async def _available_widget_ids(client: AulaApiClient) -> set[str] | None:
    """Widget IDs on this account, or None when the list could not be read."""
    if id(client) not in _WIDGET_ID_CACHE:
        try:
            widgets = await client.get_widgets()
            _WIDGET_ID_CACHE[id(client)] = {w.widget_id for w in widgets}
        except Exception as e:
            _LOGGER.warning("Could not read the widget list: %s", e)
            _WIDGET_ID_CACHE[id(client)] = None

    return _WIDGET_ID_CACHE[id(client)]


async def _first_available_widget(client: AulaApiClient, widget_ids: Sequence[str]) -> str | None:
    """Pick the first widget in ``widget_ids`` this account has.

    ``widget_ids`` is in preference order, so a school with the primary widget
    keeps using it and only the schools missing it fall back.

    A widget list that could not be read yields the preferred ID rather than
    None, matching :func:`_has_widget`: attempting the call and showing whatever
    comes back beats refusing on incomplete information.
    """
    available = await _available_widget_ids(client)
    if available is None:
        return widget_ids[0] if widget_ids else None
    return next((widget_id for widget_id in widget_ids if widget_id in available), None)


async def _require_widget(client: AulaApiClient, widget_id: str, name: str) -> bool:
    """Report a missing widget in the user's terms, and say to check `aula widgets`."""
    if await _has_widget(client, widget_id):
        return True
    print_error(
        f"the {name} widget ({widget_id}) is not on this account, "
        f"so there is nothing to fetch. Run 'aula widgets' to see what is available."
    )
    return False


async def _require_any_widget(
    client: AulaApiClient, widget_ids: Sequence[str], name: str
) -> str | None:
    """Return the usable widget ID for ``name``, or report that none is present."""
    widget_id = await _first_available_widget(client, widget_ids)
    if widget_id is not None:
        return widget_id
    listed = ", ".join(widget_ids)
    print_error(
        f"no {name} widget ({listed}) is on this account, "
        f"so there is nothing to fetch. Run 'aula widgets' to see what is available."
    )
    return None


async def _get_widget_context(
    client: AulaApiClient,
    prof: Profile,
) -> WidgetContext | None:
    try:
        return WidgetContext.from_children(prof.children, await client.get_profile_context())
    except Exception as e:
        print_error(f"preparing widget call: {e}")
        return None


def _with_child(row: dict, child: Child) -> dict:
    """Tag a provider row with the child it was fetched for.

    Providers that answer per child return bare rows, so a combined JSON
    listing would otherwise give no way to tell whose row is whose. The text
    output already prints the child, so this keeps the two output modes
    saying the same thing.
    """
    return {**row, "child_id": child.id, "child_name": child.name}


def _child_institution_filter(child: Child, fallback: list[str]) -> list[str]:
    """The child's own institution, or ``fallback`` when Aula names none."""
    return [child.institution_code] if child.institution_code else list(fallback)


def _docendo_plans_for_child(
    plans: list[DocendoWeekPlan], child: Child, *, only_child: bool
) -> list[DocendoWeekPlan]:
    """Pick the plans for the child's class, as Aula shows it in the institution profile.

    An only child gets every plan when none matches, since the class name in
    Aula can be missing or spelled in a way that does not match Docendo's.
    """
    class_name = get_in(child._raw or {}, "institutionProfile.metadata", default=None)
    matched = [plan for plan in plans if plan.matches_class(class_name)]
    return matched or (plans if only_child else [])


def _docendo_plan_lines(plan: DocendoWeekPlan) -> list[str]:
    from ..utils.html import html_to_plain

    lines = [line for line in html_to_plain(plan.note).splitlines() if line.strip()]
    current_day = None
    for lesson in plan.lessons:
        if not lesson.has_content or lesson.start_time is None:
            continue
        start = lesson.start_time.astimezone(ZoneInfo("Europe/Copenhagen"))
        if start.date() != current_day:
            current_day = start.date()
            lines.append(f"{DANISH_WEEKDAYS[start.weekday()]} {start.day}/{start.month}")
        span = start.strftime("%H:%M")
        if lesson.end_time and lesson.end_time > lesson.start_time:
            end = lesson.end_time.astimezone(ZoneInfo("Europe/Copenhagen"))
            span += f"-{end.strftime('%H:%M')}"
        lines.append(f"- {lesson.title or 'Lektion'} {span}")
        for label, value in (
            (None, lesson.description),
            ("Læringsmål", lesson.learning_goal),
            ("Elevforberedelse", lesson.notes_for_students),
        ):
            text = [line for line in html_to_plain(value).splitlines() if line.strip()]
            if text and label:
                text[0] = f"{label}: {text[0]}"
            lines.extend(f"  {line}" for line in text)
    return lines


def _thread_meta(thread: MessageThread) -> str:
    """Who takes part in a thread and when it last changed, as one line."""
    parts = []
    names = [r.full_name for r in thread.recipients if r.full_name]
    if names:
        parts.append(", ".join(names))
    if thread.last_updated:
        parts.append(thread.last_updated.strftime("%Y-%m-%d %H:%M"))
    return " | ".join(parts)
