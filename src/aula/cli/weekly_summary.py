import datetime
import enum
from collections import defaultdict
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import click

from ..api_client import AulaApiClient
from ..config import load_config
from ..const import (
    EASYIQ_WEEKPLAN_WIDGETS,
    MIN_UDDANNELSE_TASK_WIDGETS,
    MIN_UDDANNELSE_UGEPLAN_WIDGETS,
    WIDGET_DOCENDO,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_MEEBOOK,
)
from ..models import (
    Appointment,
    CalendarEvent,
    Child,
    DocendoWeekPlan,
    EasyIQHomework,
    MeebookStudentPlan,
    MUTask,
    MUWeeklyPerson,
    Profile,
)
from ..utils.diagnostics import credential_logger
from ..utils.html import html_to_plain
from ..utils.json import to_json
from ..utils.output import (
    echo,
    format_report_intro_lines,
    print_empty,
    print_error,
)
from ..widgets import EasyIQChildNotInPortal, WidgetContext, easyiq_child_user_ids
from ._app import _get_client, async_cmd, cli
from ._helpers import (
    UnreadThreads,
    _child_institution_filter,
    _children_named,
    _docendo_plan_lines,
    _docendo_plans_for_child,
    _event_slot_lines,
    _fetch_unread_threads,
    _first_available_widget,
    _has_widget,
    _print_unread_threads,
    _resolve_week,
    _with_child,
)

_LOGGER = credential_logger(__name__)


class WeeklySummaryProvider(enum.StrEnum):
    MU_OPGAVER = "mu_opgaver"
    MU_UGEPLAN = "mu_ugeplan"
    MEEBOOK = "meebook"
    DOCENDO = "docendo"
    EASYIQ = "easyiq"
    EASYIQ_HOMEWORK = "easyiq_homework"


@dataclass
class WeeklySummary:
    """What weekly-summary fetched. A provider that did not run is None."""

    events: list[CalendarEvent]
    unread: UnreadThreads
    widget_error: str | None = None
    mu_tasks: list[MUTask] | None = None
    mu_ugeplan: list[MUWeeklyPerson] | None = None
    meebook: list[MeebookStudentPlan] | None = None
    docendo: list[tuple[Child, DocendoWeekPlan]] | None = None
    easyiq_weekplan: list[tuple[Child, list[Appointment]]] | None = None
    easyiq_homework: list[tuple[Child, list[EasyIQHomework]]] | None = None


def enabled_providers(chosen: tuple[str, ...]) -> set[WeeklySummaryProvider]:
    """The providers chosen with --provider, or else those switched on in the config."""
    if chosen:
        if "all" in chosen:
            return set(WeeklySummaryProvider)
        return {WeeklySummaryProvider(p) for p in chosen}

    enabled: set[WeeklySummaryProvider] = set()
    for key, active in (load_config().get("weekly_summary") or {}).items():
        try:
            provider = WeeklySummaryProvider(key)
        except ValueError:
            _LOGGER.warning("Unknown weekly_summary provider in config: %r (ignored)", key)
            continue
        if active:
            enabled.add(provider)
    return enabled


def week_bounds(week: str) -> tuple[datetime.datetime, datetime.datetime]:
    """Monday 00:00 to Friday 23:59:59 of a ``YYYY-Wn`` week, in Danish time."""
    year_num, week_num = week.split("-W")
    tz = ZoneInfo("Europe/Copenhagen")
    start = datetime.datetime.fromisocalendar(int(year_num), int(week_num), 1).replace(tzinfo=tz)
    end = datetime.datetime.fromisocalendar(int(year_num), int(week_num), 5).replace(
        tzinfo=tz, hour=23, minute=59, second=59
    )
    return start, end


async def build_weekly_summary(
    client: AulaApiClient,
    prof: Profile,
    children: list[Child],
    week: str,
    enabled: set[WeeklySummaryProvider],
    *,
    only_selected_children: bool,
    with_thread_messages: bool,
) -> WeeklySummary:
    """Fetch the calendar, unread messages and each enabled provider's plans for ``week``.

    A failing source is logged and left empty, so one provider cannot sink the summary.
    """
    week_start, week_end = week_bounds(week)
    try:
        events = await client.get_calendar_events([c.id for c in children], week_start, week_end)
    except Exception as e:
        events = []
        _LOGGER.warning("Could not fetch calendar events: %s", e)

    summary = WeeklySummary(
        events=events,
        unread=await _fetch_unread_threads(client, with_messages=with_thread_messages),
    )
    if not enabled:
        return summary

    try:
        widget_ctx = WidgetContext.from_children(prof.children, await client.get_profile_context())
    except Exception as e:
        summary.widget_error = str(e)
        return summary
    child_filter, institution_filter, session_uuid = widget_ctx

    try:
        all_child_user_ids = easyiq_child_user_ids(await client.get_profile_context())
    except Exception as e:
        _LOGGER.warning("Could not read children for the EasyIQ child filter: %s", e)
        all_child_user_ids = []

    if only_selected_children:
        selected_user_ids = {c.user_id for c in children if c.user_id}
        child_filter = [uid for uid in child_filter if uid in selected_user_ids]

    if WeeklySummaryProvider.MU_OPGAVER in enabled and (
        widget_id := await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS)
    ):
        try:
            summary.mu_tasks = await client.widgets.get_mu_tasks(
                widget_id, child_filter, institution_filter, week, session_uuid
            )
        except Exception as e:
            summary.mu_tasks = []
            _LOGGER.warning("Could not fetch MU tasks: %s", e)

    if WeeklySummaryProvider.MU_UGEPLAN in enabled and (
        widget_id := await _first_available_widget(client, MIN_UDDANNELSE_UGEPLAN_WIDGETS)
    ):
        try:
            summary.mu_ugeplan = await client.widgets.get_ugeplan(
                widget_id, child_filter, institution_filter, week, session_uuid
            )
        except Exception as e:
            summary.mu_ugeplan = []
            _LOGGER.warning("Could not fetch MU ugeplan: %s", e)

    if WeeklySummaryProvider.MEEBOOK in enabled and await _has_widget(client, WIDGET_MEEBOOK):
        try:
            summary.meebook = await client.widgets.get_meebook_weekplan(
                child_filter, institution_filter, week, session_uuid
            )
        except Exception as e:
            summary.meebook = []
            _LOGGER.warning("Could not fetch Meebook weekplan: %s", e)

    if WeeklySummaryProvider.DOCENDO in enabled and await _has_widget(client, WIDGET_DOCENDO):
        try:
            docendo_plans = await client.widgets.get_docendo_weekplan(week)
        except Exception as e:
            docendo_plans = []
            _LOGGER.warning("Could not fetch Docendo weekplan: %s", e)
        only_child = len(prof.children) == 1
        summary.docendo = [
            (c, plan)
            for c in children
            for plan in _docendo_plans_for_child(docendo_plans, c, only_child=only_child)
        ]

    if WeeklySummaryProvider.EASYIQ in enabled and (
        widget_id := await _first_available_widget(client, EASYIQ_WEEKPLAN_WIDGETS)
    ):
        summary.easyiq_weekplan = []
        for c in children:
            if not c.user_id:
                continue
            try:
                appointments = await client.widgets.get_easyiq_weekplan(
                    week,
                    session_uuid,
                    _child_institution_filter(c, institution_filter),
                    c.user_id,
                    child_profile_id=str(c.id),
                    all_child_user_ids=all_child_user_ids,
                    all_institution_filter=institution_filter,
                    widget_id=widget_id,
                )
            except EasyIQChildNotInPortal:
                # Expected for children whose institution is not on EasyIQ.
                # The summary spans every provider, so an absence that is
                # normal does not belong in its output.
                _LOGGER.info("EasyIQ has no identity for %s; no weekly plan", c.name)
                continue
            except Exception as e:
                _LOGGER.warning("Could not fetch EasyIQ weekplan for %s: %s", c.name, e)
                continue
            if appointments:
                summary.easyiq_weekplan.append((c, appointments))

    if WeeklySummaryProvider.EASYIQ_HOMEWORK in enabled and await _has_widget(
        client, WIDGET_EASYIQ_HOMEWORK
    ):
        summary.easyiq_homework = []
        for c in children:
            if not c.user_id:
                continue
            try:
                homework = await client.widgets.get_easyiq_homework(
                    week,
                    session_uuid,
                    _child_institution_filter(c, institution_filter),
                    c.user_id,
                    child_profile_id=str(c.id),
                    all_child_user_ids=all_child_user_ids,
                    all_institution_filter=institution_filter,
                )
            except EasyIQChildNotInPortal:
                _LOGGER.info("EasyIQ has no identity for %s; no homework", c.name)
                continue
            except Exception as e:
                _LOGGER.warning("Could not fetch EasyIQ homework for %s: %s", c.name, e)
                continue
            if homework:
                summary.easyiq_homework.append((c, homework))

    return summary


def weekly_summary_json(summary: WeeklySummary, week: str, generated: datetime.datetime) -> dict:
    result: dict = {
        "week": week,
        "generated": generated.isoformat(),
        "calendar_events": [dict(ev) for ev in summary.events],
        "unread_messages": [dict(t) for t in summary.unread.threads],
    }
    if summary.mu_tasks is not None:
        result["mu_tasks"] = [dict(t) for t in summary.mu_tasks]
    if summary.mu_ugeplan is not None:
        result["mu_ugeplan"] = [dict(p) for p in summary.mu_ugeplan]
    if summary.meebook is not None:
        result["meebook_weekplan"] = [dict(s) for s in summary.meebook]
    if summary.docendo is not None:
        result["docendo_weekplan"] = [_with_child(dict(plan), c) for c, plan in summary.docendo]
    if summary.easyiq_weekplan is not None:
        result["easyiq_weekplan"] = [
            _with_child(dict(a), c) for c, appts in summary.easyiq_weekplan for a in appts
        ]
    if summary.easyiq_homework is not None:
        result["easyiq_homework"] = [
            _with_child(dict(hw), c) for c, items in summary.easyiq_homework for hw in items
        ]
    return result


def _print_calendar(events: list[CalendarEvent], week_start: datetime.datetime) -> None:
    echo("Calendar events")
    echo()
    if not events:
        print_empty("calendar events")
        echo()
        return

    by_day: dict[datetime.date, list[CalendarEvent]] = defaultdict(list)
    for ev in events:
        by_day[ev.start_datetime.date()].append(ev)
    for day_offset in range(5):
        day = week_start + datetime.timedelta(days=day_offset)
        echo(day.strftime("%A, %d %B"))
        for line in _event_slot_lines(by_day.get(day.date(), [])) or ["- (no events)"]:
            echo(line)
        echo()


def _print_providers(summary: WeeklySummary) -> None:
    if summary.mu_tasks is not None:
        echo("Homework & tasks (Min Uddannelse)")
        echo()
        for task in summary.mu_tasks:
            parts = []
            if task.weekday:
                parts.append(task.weekday)
            subjects = ", ".join(cls.subject_name for cls in task.classes if cls.subject_name)
            if subjects:
                parts.append(subjects)
            label = f"{' – '.join(parts)}: {task.title}" if parts else task.title
            status = " ✓" if task.is_completed else ""
            echo(f"- {label}{status}")
            if task.task_type:
                echo(f"  Type: {task.task_type}")
        if not summary.mu_tasks:
            print_empty("tasks")
        echo()

    if summary.mu_ugeplan:
        echo("Weekly letter (Min Uddannelse ugeplan)")
        echo()
        for person in summary.mu_ugeplan:
            for inst in person.institutions:
                for letter in inst.letters:
                    echo(f"{person.name} - {letter.group_name} ({inst.name})")
                    echo()
                    for line in html_to_plain(letter.content_html).splitlines():
                        echo(line)
                    echo()

    if summary.meebook:
        echo("Weekly plan (Meebook)")
        echo()
        for student in summary.meebook:
            echo(student.name)
            echo()
            for day in student.week_plan:
                if not day.tasks:
                    continue
                echo(day.date)
                for task in day.tasks:
                    label = task.title or task.type
                    if task.pill:
                        label = f"[{task.pill}] {label}"
                    echo(f"- {label}")
                    _echo_html_lines(task.content)
            echo()

    if summary.docendo:
        echo("Weekly plan (Docendo)")
        echo()
        for c, plan in summary.docendo:
            echo(f"{c.name} ({plan.name})")
            echo()
            for line in _docendo_plan_lines(plan):
                echo(line)
            echo()

    if summary.easyiq_weekplan:
        echo("Weekly plan (EasyIQ)")
        echo()
        for c, appointments in summary.easyiq_weekplan:
            echo(c.name)
            echo()
            for appt in appointments:
                echo(f"- {appt.title}")
                if appt.start or appt.end:
                    echo(f"  {appt.start} – {appt.end}")
                _echo_html_lines(appt.description)
            echo()

    if summary.easyiq_homework:
        echo("Homework (EasyIQ)")
        echo()
        for c, homework in summary.easyiq_homework:
            echo(c.name)
            echo()
            for hw in homework:
                status = "[x]" if hw.is_completed else "[ ]"
                echo(f"- {status} {hw.title}")
                if hw.subject:
                    echo(f"  Subject: {hw.subject}")
                if hw.due_date:
                    echo(f"  Due: {hw.due_date}")
                _echo_html_lines(hw.description)
            echo()


def _echo_html_lines(html: str | None) -> None:
    if html:
        for line in html_to_plain(html).splitlines():
            if line.strip():
                echo(f"  {line}")


@cli.command("weekly-summary")
@click.option(
    "--child",
    type=str,
    default=None,
    help="Child name (partial, case-insensitive). Defaults to all children.",
)
@click.option(
    "--week",
    type=str,
    default=None,
    help="Week number (e.g. 8) or full format (2026-W8). Defaults to current week.",
)
@click.option(
    "--provider",
    "providers",
    multiple=True,
    type=click.Choice([p.value for p in WeeklySummaryProvider] + ["all"]),
    help="Provider to enable for this run (overrides config). Use 'all' for every provider.",
)
@click.pass_context
@async_cmd
async def weekly_summary(ctx, child, week, providers):
    """Generate a weekly overview for a child, formatted for AI consumption.

    Aggregates calendar events, homework tasks, and weekly plans from all
    configured providers. Output can be pasted directly into an AI assistant.
    """
    is_json = ctx.obj.get("OUTPUT_FORMAT") == "json"
    week = _resolve_week(week)
    enabled = enabled_providers(providers)
    week_start, week_end = week_bounds(week)

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        children = _children_named(prof.children, child)
        if not children:
            names = ", ".join(c.name for c in prof.children)
            print_error(f"no child matching '{child}'. Available: {names}")
            return

        now = datetime.datetime.now(ZoneInfo("Europe/Copenhagen"))
        summary = await build_weekly_summary(
            client,
            prof,
            children,
            week,
            enabled,
            only_selected_children=bool(child),
            with_thread_messages=not is_json,
        )

    if is_json:
        if summary.widget_error is not None:
            print_error(f"preparing widget call: {summary.widget_error}")
        echo(to_json(weekly_summary_json(summary, week, now)))
        return

    year_num, week_num = week.split("-W")
    for line in format_report_intro_lines(
        f"Weekly overview - week {week_num}, {year_num}",
        [
            ("Generated", now.strftime("%Y-%m-%d")),
            ("Period", f"{week_start.strftime('%a %d %b')} - {week_end.strftime('%a %d %b %Y')}"),
        ],
    ):
        echo(line)
    echo()

    _print_calendar(summary.events, week_start)
    _print_unread_threads(summary.unread)
    if summary.widget_error is not None:
        print_error(f"preparing widget call: {summary.widget_error}")
        echo("(Widget context unavailable – skipping provider data)")
        return
    _print_providers(summary)
