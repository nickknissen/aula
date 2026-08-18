"""Structural probe of the EasyIQ portal, safe to paste into a public issue.

EasyIQ's portal is undocumented and behaves differently per institution: which
identifier it accepts as ``loginId``, which controller carries homework, and
even the casing of the JSON keys have all had to be learned from users running
the CLI against their own accounts. This module asks those questions in one
pass and reports only the *shape* of what came back.

Nothing here prints a name, a subject, a description or an ID. Identifiers are
reported as comparisons ("EasyIQ's Id equals the Aula institution profile ID")
because that is the fact the code needs, and it carries no personal data. Raw
bodies are available behind an explicit opt-in for local debugging only.
"""

from dataclasses import dataclass, field
from typing import Any

from ..const import (
    EASYIQ_CALENDAR_PATH,
    EASYIQ_CHILDREN_PATH,
    EASYIQ_HOMEWORK_PATH,
    EASYIQ_PORTAL,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_EASYIQ_WEEKPLAN,
)
from .mapping import get_in

#: The controllers to probe, with the query parameters each one expects.
PROBE_TARGETS = (
    (
        EASYIQ_CALENDAR_PATH,
        WIDGET_EASYIQ_WEEKPLAN,
        {"activityFilter": "-1", "courseFilter": "-1", "textFilter": "", "ownWeekPlan": "false"},
    ),
    (EASYIQ_HOMEWORK_PATH, WIDGET_EASYIQ_HOMEWORK, {"activityFilter": ""}),
)


@dataclass
class Attempt:
    """One controller called with one identifier combination."""

    login_id_source: str
    child_header_source: str
    status: int | None = None
    error: str = ""
    rows: int | None = None
    item_types: dict[str, int] = field(default_factory=dict)
    keys: list[str] = field(default_factory=list)
    body: Any = None


@dataclass
class ChildProbe:
    """Everything learned about one child."""

    label: str
    easyiq_entry_found: bool = False
    easyiq_id_matches: list[str] = field(default_factory=list)
    attempts: dict[str, list[Attempt]] = field(default_factory=dict)


@dataclass
class ProbeReport:
    widgets: list[tuple[str, str, str]] = field(default_factory=list)
    tokens: dict[str, str] = field(default_factory=dict)
    children_status: int | None = None
    children_error: str = ""
    children_count: int | None = None
    children_fields: list[str] = field(default_factory=list)
    children: list[ChildProbe] = field(default_factory=list)


def _describe_rows(payload: Any) -> tuple[int | None, dict[str, int], list[str]]:
    """Summarise a response as (row count, item type histogram, first row keys)."""
    rows = payload if isinstance(payload, list) else None
    if rows is None and isinstance(payload, dict):
        for key in ("events", "calendarEvents", "items", "data", "result", "Children"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
    if rows is None:
        return None, {}, []

    dicts = [row for row in rows if isinstance(row, dict)]
    histogram: dict[str, int] = {}
    for row in dicts:
        folded = {str(k).lower(): v for k, v in row.items()}
        item_type = folded.get("itemtype", folded.get("type"))
        name = "missing" if item_type is None else str(item_type)
        histogram[name] = histogram.get(name, 0) + 1
    keys = [str(key) for key in dicts[0]] if dicts else []
    return len(rows), histogram, keys


def _entries(payload: Any) -> list[dict[str, Any]]:
    """Return the child entries from a ``GetChildren`` payload."""
    if isinstance(payload, dict):
        for key in ("Children", "children"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _match_easyiq_entry(
    entries: list[dict[str, Any]], aula_ids: dict[str, str]
) -> tuple[bool, list[str]]:
    """Find this child among EasyIQ's own list and say which Aula ID its Id equals.

    Returns ``(found, matches)`` where ``matches`` names the Aula identifiers
    that EasyIQ's ``Id`` is equal to. An empty list on a found entry means
    EasyIQ uses an ID of its own, which is the case worth knowing about.
    """
    wanted = {str(value).casefold() for value in aula_ids.values() if value}
    for entry in entries:
        folded = {str(k).lower(): str(v) for k, v in entry.items()}
        identifying = {folded.get("login", ""), folded.get("id", "")}
        if not {value.casefold() for value in identifying if value} & wanted:
            continue
        easyiq_id = folded.get("id", "")
        return True, [name for name, value in aula_ids.items() if value and value == easyiq_id]
    return False, []


async def probe_easyiq(
    client: Any,
    children: list[Any],
    guardian_login: str,
    date: str,
    institution_filter: list[str] | None = None,
    all_child_user_ids: list[str] | None = None,
    include_values: bool = False,
) -> ProbeReport:
    """Run the probe and return its report.

    ``date`` is an ISO timestamp inside the week to ask about.
    ``institution_filter`` and ``all_child_user_ids`` must be the same values
    the real commands send: EasyIQ answers differently without them, so a
    probe that omitted either would report failures the working code never
    sees.
    """
    institution_filter = institution_filter or []
    all_child_user_ids = all_child_user_ids or []
    report = ProbeReport()

    try:
        widgets = await client.get_widgets()
        report.widgets = [
            (w.widget_id, w.name, w.widget_type)
            for w in widgets
            if "easyiq" in (w.name or "").casefold()
            or "easyiq" in (w.widget_supplier or "").casefold()
        ]
    except Exception as e:
        report.widgets = []
        report.tokens["widget list"] = f"failed: {type(e).__name__}"

    tokens: dict[str, str] = {}
    for widget_id in (WIDGET_EASYIQ_WEEKPLAN, WIDGET_EASYIQ_HOMEWORK):
        try:
            tokens[widget_id] = await client.widgets._get_bearer_token(widget_id)
            report.tokens[widget_id] = "ok"
        except Exception as e:
            report.tokens[widget_id] = f"failed: {type(e).__name__}"

    if not tokens:
        return report

    # Establish the portal session first: without it every controller 500s,
    # so a probe that skipped it would report nothing but failures.
    await client.widgets.ensure_easyiq_session(
        institution_filter, guardian_login, all_child_user_ids
    )

    any_token = next(iter(tokens.values()))
    headers = client.widgets.easyiq_headers(
        any_token, institution_filter, guardian_login, all_child_user_ids
    )
    entries: list[dict[str, Any]] = []
    try:
        resp = await client._request_with_version_retry(
            "get", f"{EASYIQ_PORTAL}{EASYIQ_CHILDREN_PATH}", headers=headers
        )
        report.children_status = resp.status_code
        entries = _entries(resp.json())
        report.children_count = len(entries)
        report.children_fields = [str(key) for key in entries[0]] if entries else []
    except Exception as e:
        report.children_error = f"{type(e).__name__}: {e}"

    for index, child in enumerate(children, start=1):
        raw = child._raw or {}
        aula_ids = {
            "institution_profile_id": str(child.id),
            "profile_id": str(child.profile_id),
            "user_id": str(raw.get("userId", "")),
        }
        probe = ChildProbe(label=f"Child {index} of {len(children)}")
        probe.easyiq_entry_found, probe.easyiq_id_matches = _match_easyiq_entry(entries, aula_ids)

        c_institutions: list[str] = []
        inst_code = get_in(raw, "institutionProfile.institutionCode", default="")
        if inst_code:
            c_institutions.append(str(inst_code))

        for path, widget_id, extra_params in PROBE_TARGETS:
            token = tokens.get(widget_id)
            if token is None:
                continue
            base = client.widgets.easyiq_headers(
                token,
                c_institutions or institution_filter,
                guardian_login,
                all_child_user_ids,
                aula_ids["user_id"],
            )
            easyiq_id = client.widgets.resolve_easyiq_child_id(aula_ids["user_id"])
            named = {**aula_ids, "easyiq_id": easyiq_id or ""}
            attempts: list[Attempt] = []
            for login_id, child_header in client.widgets.easyiq_identifier_variants(
                aula_ids["institution_profile_id"],
                aula_ids["user_id"],
                guardian_login,
                easyiq_id,
            ):
                attempt = Attempt(
                    login_id_source=_name_of(login_id, named, guardian_login),
                    child_header_source=_name_of(child_header, named, guardian_login),
                )
                try:
                    resp = await client._request_with_version_retry(
                        "get",
                        f"{EASYIQ_PORTAL}{path}",
                        params={**extra_params, "date": date, "loginId": login_id},
                        # x-childfilter stays the full list from base.
                        headers={**base, "x-child": child_header},
                    )
                    attempt.status = resp.status_code
                    payload = resp.json()
                    attempt.rows, attempt.item_types, attempt.keys = _describe_rows(payload)
                    if include_values:
                        attempt.body = payload
                except Exception as e:
                    attempt.error = f"{type(e).__name__}: {e}"
                attempts.append(attempt)
            probe.attempts[path] = attempts

        report.children.append(probe)

    return report


def _name_of(value: str, aula_ids: dict[str, str], guardian_login: str) -> str:
    """Name an identifier by where it came from, so no ID is printed."""
    for name, candidate in aula_ids.items():
        if candidate and candidate == value:
            return name
    if value == guardian_login:
        return "guardian_login"
    return "unknown"


def render_report(report: ProbeReport, include_values: bool = False) -> list[str]:
    """Render the report as lines, safe to paste unless ``include_values``."""
    lines = ["EasyIQ probe", "============", ""]

    if report.widgets:
        lines.append("Widgets:")
        lines.extend(f"  {wid}  {name}  ({wtype})" for wid, name, wtype in report.widgets)
    else:
        lines.append("Widgets: no EasyIQ widget on this account")
    lines.append("Tokens: " + ", ".join(f"{k} {v}" for k, v in report.tokens.items()))
    lines.append("")

    lines.append(f"{EASYIQ_CHILDREN_PATH}")
    if report.children_error:
        lines.append(f"  failed: {report.children_error}")
    else:
        lines.append(f"  status {report.children_status}, {report.children_count} entries")
        if report.children_fields:
            lines.append(f"  fields: {', '.join(report.children_fields)}")
    lines.append("")

    for probe in report.children:
        lines.append(probe.label)
        if not probe.easyiq_entry_found:
            lines.append("  not listed by EasyIQ (likely not an EasyIQ institution)")
        elif probe.easyiq_id_matches:
            lines.append(f"  EasyIQ Id equals the Aula {' and '.join(probe.easyiq_id_matches)}")
        else:
            lines.append("  listed by EasyIQ, but its Id matches no Aula identifier")

        for path, attempts in probe.attempts.items():
            lines.append(f"  {path}")
            for attempt in attempts:
                label = f"loginId={attempt.login_id_source} child={attempt.child_header_source}"
                if attempt.error:
                    lines.append(f"    {label}  {attempt.error}")
                    continue
                detail = f"    {label}  {attempt.status}"
                if attempt.rows is not None:
                    detail += f"  {attempt.rows} rows  itemType {attempt.item_types or '{}'}"
                lines.append(detail)
                if attempt.keys:
                    lines.append(f"      keys: {', '.join(attempt.keys)}")
                if include_values and attempt.body is not None:
                    lines.append(f"      body: {attempt.body}")
        lines.append("")

    if not include_values:
        lines.append("No names, subjects or IDs are included above.")
    else:
        lines.append("WARNING: --include-values printed raw responses. Do not paste this publicly.")
    return lines
