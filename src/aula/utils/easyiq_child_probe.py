"""Per-child EasyIQ request/response inspection, for issue #68.

The bug reporter established that the ``loginId`` query param on
``CalendarGetWeekplanEvents`` is the *parent's* ID, constant across every
child, and that the child is actually selected by the ``x-child`` header (and,
possibly, by a preceding ``POST /Aula/SwitchChild``). This module runs the
real request for each child in turn and reports exactly what was sent and
what came back, plus a cross-child overlap check: if two children's answers
ever share an ``Id``, one of them was answered with (partly) the wrong data.

Nothing here prints a child's name, a title, a description, or a real
identifier value (UniLogin, parent login id, EasyIQ id, ...) unless
``include_values`` is explicitly requested, and the bearer token is never
printed at all, even then. By default every identifier-shaped header and
query-param value is replaced with a stable symbolic placeholder (built by
:func:`_build_named_registry` / :func:`_name_of`) so the reader can still see
whether two children's requests used the SAME underlying value or DIFFERENT
ones -- which is the whole diagnostic point -- without ever seeing the value
itself. A handful of genuinely non-sensitive fields (institution codes,
filter flags, the date, ...) are always left literal so the output stays
readable.
"""

from dataclasses import dataclass, field
from typing import Any

from ..const import EASYIQ_CALENDAR_PATH, EASYIQ_PORTAL, WIDGET_EASYIQ_WEEKPLAN
from ..models import EasyIQCalendarEvent
from .mapping import get_in
from .week import monday_of_week

#: Same params the real weekly-plan controller call sends; see
#: ``AulaWidgetsClient.get_easyiq_calendar_events``.
_EXTRA_PARAMS = {
    "activityFilter": "-1",
    "courseFilter": "-1",
    "textFilter": "",
    "ownWeekPlan": "false",
}

#: Query-param and header keys that are never identifier-shaped -- filter
#: flags, the date, and institution codes, which are school-level rather
#: than personal -- so they stay literal even in the default, redacted
#: output. Everything else is treated as identifier-shaped and symbolised
#: by default (see :func:`_symbolise`).
_LITERAL_PARAM_KEYS = {"activityfilter", "coursefilter", "textfilter", "ownweekplan", "date"}
_LITERAL_HEADER_KEYS = {
    "accept",
    "x-requested-with",
    "referer",
    "x-userprofile",
    "x-institutionfilter",
}


def _rows_from_payload(payload: Any) -> list[dict[str, Any]] | None:
    """Pull the row list out of the calendar controller's answer, or None."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("events", "calendarEvents", "items", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return None


def _name_of(value: str, named: dict[str, str]) -> str:
    """Name an identifier by where it came from, so no ID is printed."""
    for name, candidate in named.items():
        if candidate and candidate == value:
            return name
    return "unknown"


def _symbolise(value: str, named: dict[str, str]) -> str:
    """Replace an identifier-shaped value with its stable placeholder.

    ``x-childfilter`` carries all of the guardian's children as one
    comma-joined string, so each comma-separated part is named on its own;
    everything else is a single value. The same underlying value always
    gets the same placeholder (via ``named``), so two children's requests
    can still be compared for SAME vs. DIFFERENT without printing either
    child's real identifier.
    """
    if not value:
        return value
    if "," in value:
        return ",".join(_name_of(part, named) if part else part for part in value.split(","))
    return _name_of(value, named)


def _build_named_registry(children: list[Any], client: Any, guardian_login: str) -> dict[str, str]:
    """Build one name->value map for every identifier in the whole report.

    Built once, up front, and shared across every child so that the same
    real value always maps to the same placeholder wherever it shows up
    (a child's own ``x-child`` header, another child's ``x-childfilter``
    entry, ...) -- that consistency is what lets a reader tell whether two
    children's requests genuinely used the same identifier.
    """
    named: dict[str, str] = {
        "guardian_login": guardian_login,
        "parent_login_id": client.widgets._easyiq_parent_login_id or "",
    }
    for index, child in enumerate(children, start=1):
        raw = child._raw or {}
        child_user_id = str(raw.get("userId", ""))
        named[f"child{index}_user_id"] = child_user_id
        named[f"child{index}_real_login"] = (
            client.widgets.resolve_easyiq_child_login(child_user_id) or ""
        )
        named[f"child{index}_easyiq_id"] = (
            client.widgets.resolve_easyiq_child_id(child_user_id) or ""
        )
        named[f"child{index}_profile_id"] = str(child.id)
    return named


@dataclass
class ChildRequestReport:
    """Everything learned about one child's request and response."""

    label: str
    switch_child: str = ""
    identifier_variant: str = ""
    url: str = ""
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    status: int | None = None
    error: str = ""
    row_count: int = 0
    unique_id_count: int = 0
    activities_display: list[str] = field(default_factory=list)
    item_types: list[str] = field(default_factory=list)
    values: list[dict[str, str]] = field(default_factory=list)
    #: Never rendered directly -- only its overlap with other children's is.
    ids: set[str] = field(default_factory=set)


@dataclass
class ChildProbeReport:
    switch_child_enabled: bool = False
    children: list[ChildRequestReport] = field(default_factory=list)


async def probe_easyiq_children(
    client: Any,
    children: list[Any],
    guardian_login: str,
    week: str,
    institution_filter: list[str],
    all_child_user_ids: list[str],
    *,
    switch_child: bool = False,
    include_values: bool = False,
) -> ChildProbeReport:
    """Read one week from EasyIQ's weekly-plan controller for each child.

    ``institution_filter`` and ``all_child_user_ids`` must be the same values
    the real commands send, for the same reason :func:`easyiq_probe.probe_easyiq`
    needs them: EasyIQ answers differently without them.

    When ``switch_child`` is set, ``POST /Aula/SwitchChild`` is sent with this
    child's EasyIQ ``Id`` before the read, which is the sequencing the real
    client always uses. With it off, only the ``x-child`` header varies.
    """
    report = ChildProbeReport(switch_child_enabled=switch_child)
    date = monday_of_week(week)
    url = f"{EASYIQ_PORTAL}{EASYIQ_CALENDAR_PATH}"

    await client.widgets.ensure_easyiq_session(
        institution_filter, guardian_login, all_child_user_ids
    )
    token = await client.widgets._get_bearer_token(WIDGET_EASYIQ_WEEKPLAN)
    named = _build_named_registry(children, client, guardian_login)

    for index, child in enumerate(children, start=1):
        raw = child._raw or {}
        child_user_id = str(raw.get("userId", ""))
        child_profile_id = str(child.id)
        entry = ChildRequestReport(label=f"Child {index} of {len(children)}")

        c_institutions: list[str] = []
        inst_code = get_in(raw, "institutionProfile.institutionCode", default="")
        if inst_code:
            c_institutions.append(str(inst_code))
        effective_institutions = c_institutions or institution_filter

        easyiq_id = client.widgets.resolve_easyiq_child_id(child_user_id)
        if switch_child:
            if easyiq_id:
                try:
                    await client.widgets.switch_easyiq_child(
                        easyiq_id,
                        effective_institutions,
                        guardian_login,
                        all_child_user_ids,
                        child_user_id,
                    )
                    entry.switch_child = "ok"
                except Exception as e:
                    entry.switch_child = f"failed: {type(e).__name__}: {e}"
            else:
                entry.switch_child = "skipped: no EasyIQ Id resolved for this child"

        variants = client.widgets.easyiq_identifier_variants(
            child_profile_id, child_user_id, guardian_login, easyiq_id
        )

        success: tuple[Any, ...] | None = None
        first_empty: tuple[Any, ...] | None = None
        last_error: Exception | None = None

        for login_id, child_header in variants:
            headers = client.widgets.easyiq_headers(
                token, effective_institutions, guardian_login, all_child_user_ids, child_header
            )
            params = {**_EXTRA_PARAMS, "date": date, "loginId": login_id}
            try:
                resp = await client._request_with_version_retry(
                    "get", url, params=params, headers=headers
                )
                resp.raise_for_status()
                payload = resp.json()
            except Exception as e:
                last_error = e
                continue

            rows = _rows_from_payload(payload)
            if rows is None:
                continue

            events = [EasyIQCalendarEvent.from_dict(row) for row in rows]
            attempt = (login_id, child_header, headers, params, resp.status_code, events)
            if events:
                success = attempt
                break
            if first_empty is None:
                first_empty = attempt

        chosen = success or first_empty
        if chosen is None:
            entry.error = (
                f"{type(last_error).__name__}: {last_error}"
                if last_error is not None
                else "no identifier variant returned a readable response"
            )
        else:
            login_id, child_header, headers, params, status, events = chosen
            entry.url = url
            if include_values:
                entry.params = dict(params)
                entry.headers = {
                    key: ("REDACTED" if key.lower() == "authorization" else value)
                    for key, value in headers.items()
                }
            else:
                entry.params = {
                    key: (value if key.lower() in _LITERAL_PARAM_KEYS else _symbolise(value, named))
                    for key, value in params.items()
                }
                entry.headers = {
                    key: (
                        "REDACTED"
                        if key.lower() == "authorization"
                        else value
                        if key.lower() in _LITERAL_HEADER_KEYS
                        else _symbolise(value, named)
                    )
                    for key, value in headers.items()
                }
            entry.identifier_variant = (
                f"loginId={_name_of(login_id, named)} child={_name_of(child_header, named)}"
            )
            entry.status = status
            entry.row_count = len(events)
            ids = {event.event_id for event in events if event.event_id}
            entry.ids = ids
            entry.unique_id_count = len(ids)
            entry.activities_display = sorted({e.activities for e in events if e.activities})
            entry.item_types = sorted({str(e.item_type) for e in events if e.item_type is not None})
            if include_values:
                entry.values = [{"title": e.title, "description": e.description} for e in events]

        report.children.append(entry)

    return report


def render_child_report(report: ChildProbeReport, include_values: bool = False) -> list[str]:
    """Render the report as lines, safe to paste unless ``include_values``."""
    lines = ["EasyIQ per-child request inspection", "====================================", ""]
    lines.append(
        f"--switch-child: {'on' if report.switch_child_enabled else 'off'} "
        "(POST /Aula/SwitchChild before each child's read)"
    )
    lines.append("")

    for entry in report.children:
        lines.append(entry.label)
        if entry.switch_child:
            lines.append(f"  SwitchChild: {entry.switch_child}")

        if not entry.url:
            lines.append(f"  failed: {entry.error or 'no readable response'}")
            lines.append("")
            continue

        lines.append(f"  identifier variant used: {entry.identifier_variant}")
        lines.append(f"  GET {entry.url}")
        lines.append("  params:")
        for key, value in entry.params.items():
            lines.append(f"    {key}={value}")
        lines.append("  headers:")
        for key, value in entry.headers.items():
            lines.append(f"    {key}: {value}")
        lines.append(f"  status: {entry.status}")
        lines.append(
            f"  summary: {entry.row_count} item(s), {entry.unique_id_count} unique Id value(s)"
        )
        lines.append(
            "  ActivitiesDisplay values: " + (", ".join(entry.activities_display) or "(none)")
        )
        lines.append("  ItemType values: " + (", ".join(entry.item_types) or "(none)"))
        if include_values:
            for value in entry.values:
                title = value["title"] or "(no title)"
                lines.append(f"    - {title}: {value['description'] or '(no description)'}")
        lines.append("")

    lines.append("Overlap matrix (shared Id count between each pair of children):")
    lines.append("  Zero everywhere is correct. Any non-zero cell means two children were")
    lines.append("  answered with (partly) the same data -- that is the bug this checks for.")
    count = len(report.children)
    if count < 2:
        lines.append("  (only one child with a readable response; nothing to compare)")
    else:
        col = 6
        lines.append(" " * col + "".join(f"{f'C{i + 1}':>{col}}" for i in range(count)))
        for i in range(count):
            cells = "".join(
                f"{'-':>{col}}"
                if i == j
                else f"{len(report.children[i].ids & report.children[j].ids):>{col}}"
                for j in range(count)
            )
            lines.append(f"{f'C{i + 1}':<{col}}" + cells)
    lines.append("")

    if not include_values:
        lines.append(
            "No child names, titles, descriptions or bearer token are included above. "
            "Header and query-param values that identify a person (UniLogin, parent login "
            "id, guardian login, EasyIQ id, ...) are shown as stable placeholders like "
            "'child2_user_id' instead of the real value -- the same placeholder always means "
            "the same underlying value, so SAME vs. DIFFERENT is still visible."
        )
    else:
        lines.append(
            "WARNING: --include-values printed titles, descriptions, and every real "
            "identifier value (UniLogin, parent login id, ...) in place of the placeholders "
            "above. Do not paste this publicly."
        )
    return lines
