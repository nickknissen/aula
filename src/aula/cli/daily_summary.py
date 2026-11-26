import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import click

from ..api_client import AulaApiClient
from ..const import MIN_UDDANNELSE_TASK_WIDGETS
from ..models import (
    CalendarEvent,
    Child,
    DailyOverview,
    DayTemplate,
    MUTask,
    Profile,
)
from ..utils.diagnostics import credential_logger
from ..utils.json import to_json
from ..utils.output import (
    echo,
    format_report_intro_lines,
    print_empty,
    print_error,
)
from ..utils.week import DANISH_WEEKDAYS
from ..widgets import WidgetContext
from ._app import _get_client, async_cmd, cli
from ._helpers import (
    UnreadThreads,
    _children_named,
    _event_slot_lines,
    _fetch_unread_threads,
    _first_available_widget,
    _print_unread_threads,
)

_LOGGER = credential_logger(__name__)


@dataclass
class ChildDay:
    child: Child
    #: Aula's live state, only fetched when the day is today.
    overview: DailyOverview | None
    #: The planned times for the day.
    template: DayTemplate | None


@dataclass
class DailySummary:
    children: list[ChildDay]
    events: list[CalendarEvent]
    tasks_due: list[MUTask]
    unread: UnreadThreads
    widget_error: str | None = None


async def _day_templates(
    client: AulaApiClient, children: list[Child], day: datetime.date
) -> dict[int, DayTemplate]:
    try:
        templates = await client.get_presence_templates([c.id for c in children], day, day)
    except Exception as e:
        templates = []
        _LOGGER.warning("Could not fetch presence templates: %s", e)

    _LOGGER.debug("=== ID MAPPING VERIFICATION ===")
    _LOGGER.debug("Children and their IDs:")
    for c in children:
        _LOGGER.debug("  Child: %s | id=%s | profile_id=%s", c.name, c.id, c.profile_id)
    _LOGGER.debug("Presence templates and their institution profile IDs:")
    for tmpl in templates:
        if tmpl.institution_profile:
            _LOGGER.debug(
                "  Template: %s | id=%s | profile_id=%s",
                tmpl.institution_profile.name or "unknown",
                tmpl.institution_profile.id,
                tmpl.institution_profile.profile_id,
            )
    _LOGGER.debug("=== END ID MAPPING VERIFICATION ===")

    by_child: dict[int, DayTemplate] = {}
    for tmpl in templates:
        if not tmpl.institution_profile:
            _LOGGER.warning("Presence template has no institution profile, skipping")
            continue
        if not tmpl.day_templates:
            _LOGGER.warning(
                "Presence template for %s has no day templates", tmpl.institution_profile.name
            )
            continue
        matching = [d for d in tmpl.day_templates if d.by_date == day.isoformat()]
        if matching and tmpl.institution_profile.id is not None:
            by_child[tmpl.institution_profile.id] = matching[0]
    return by_child


async def build_daily_summary(
    client: AulaApiClient,
    prof: Profile,
    children: list[Child],
    day: datetime.datetime,
    *,
    is_today: bool,
    only_selected_children: bool,
    with_thread_messages: bool,
) -> DailySummary:
    """Fetch each child's status and plan, the day's events, homework due and unread messages.

    ``day`` is midnight of the day in Danish time. Aula's daily overview only
    describes today, so it is fetched only when ``is_today``.
    """
    templates = await _day_templates(client, children, day.date())

    child_days = []
    for c in children:
        overview = None
        if is_today:
            try:
                overview = await client.get_daily_overview(c.id)
            except Exception as e:
                _LOGGER.warning("Could not fetch daily overview for %s: %s", c.name, e)
        child_days.append(ChildDay(c, overview, templates.get(c.id)))

    try:
        events = await client.get_calendar_events(
            [c.id for c in children],
            day.replace(hour=0, minute=0, second=0, microsecond=0),
            day.replace(hour=23, minute=59, second=59, microsecond=0),
        )
    except Exception as e:
        events = []
        _LOGGER.warning("Could not fetch calendar events: %s", e)

    widget_error = None
    try:
        widget_ctx = WidgetContext.from_children(prof.children, await client.get_profile_context())
    except Exception as e:
        widget_ctx = None
        widget_error = str(e)

    tasks_due: list[MUTask] = []
    mu_task_widget = await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS)
    if widget_ctx is not None and mu_task_widget is not None:
        child_filter, institution_filter, session_uuid = widget_ctx
        if only_selected_children:
            selected_user_ids = {c.user_id for c in children if c.user_id}
            child_filter = [uid for uid in child_filter if uid in selected_user_ids]

        iso = day.isocalendar()
        try:
            all_tasks = await client.widgets.get_mu_tasks(
                mu_task_widget,
                child_filter,
                institution_filter,
                f"{iso[0]}-W{iso[1]}",
                session_uuid,
            )
        except Exception as e:
            all_tasks = []
            _LOGGER.warning("Could not fetch tasks: %s", e)

        weekday = DANISH_WEEKDAYS[day.weekday()]
        tasks_due = [
            t
            for t in all_tasks
            if t.weekday == weekday or (t.due_date and t.due_date.date() == day.date())
        ]

    return DailySummary(
        children=child_days,
        events=events,
        tasks_due=tasks_due,
        unread=await _fetch_unread_threads(client, with_messages=with_thread_messages),
        widget_error=widget_error,
    )


def daily_summary_json(
    summary: DailySummary, day: datetime.datetime, generated: datetime.datetime
) -> dict:
    status = []
    for child_day in summary.children:
        entry: dict = {"child": dict(child_day.child)}
        if child_day.overview is not None:
            entry["overview"] = dict(child_day.overview)
        if child_day.template:
            entry["presence_template"] = dict(child_day.template)
        status.append(entry)
    return {
        "date": day.date().isoformat(),
        "generated": generated.isoformat(),
        "status": status,
        "calendar_events": [dict(ev) for ev in summary.events],
        "homework_due_today": [dict(t) for t in summary.tasks_due],
        "unread_messages": [dict(t) for t in summary.unread.threads],
    }


def _print_child_day(child_day: ChildDay) -> None:
    ov, day_tmpl = child_day.overview, child_day.template
    echo(child_day.child.name)

    if ov is not None:
        status = ov.status.display_name if ov.status else "Unknown"
        echo(f"- Status: {status}")
        if ov.check_in_time:
            echo(f"- Check-in: {ov.check_in_time}")
        if ov.check_out_time:
            echo(f"- Check-out: {ov.check_out_time}")
        if ov.location and ov.location.name:
            echo(f"- Location: {ov.location.name}")
        if ov.main_group:
            echo(f"- Group: {ov.main_group.name}")

    # Show actual times from daily overview, with planned times as fallback
    if ov is not None and ov.entry_time:
        echo(f"- Entry: {ov.entry_time}")
    elif day_tmpl and day_tmpl.entry_time:
        echo(f"- Planned entry: {day_tmpl.entry_time}")

    if ov is not None and ov.exit_time:
        echo(f"- Exit: {ov.exit_time}")
    elif day_tmpl and day_tmpl.exit_time:
        echo(f"- Planned exit: {day_tmpl.exit_time}")

    if ov is not None and ov.exit_with:
        echo(f"- Picked up by: {ov.exit_with}")
    elif day_tmpl and day_tmpl.exit_with:
        echo(f"- Picked up by (planned): {day_tmpl.exit_with}")

    if ov is not None and ov.comment:
        echo(f"- Note: {ov.comment}")

    if day_tmpl and day_tmpl.spare_time_activity:
        sta = day_tmpl.spare_time_activity
        if sta.start_time and sta.end_time:
            activity_line = f"- Activity: {sta.start_time}–{sta.end_time}"
            if sta.comment:
                activity_line = f"{activity_line}  ({sta.comment})"
            echo(activity_line)

    if ov is None and not day_tmpl:
        echo("- No data available")

    echo()


@cli.command("daily-summary")
@click.option(
    "--child",
    type=str,
    default=None,
    help="Child name (partial, case-insensitive). Defaults to all children.",
)
@click.option(
    "--date",
    "target_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Date to summarise (YYYY-MM-DD). Defaults to today.",
)
@click.pass_context
@async_cmd
async def daily_summary(ctx, child, target_date):
    """Generate a daily overview for today, formatted for AI consumption.

    Includes check-in status, today's schedule, homework due today,
    and unread messages. Output can be pasted directly into an AI assistant.
    """
    is_json = ctx.obj.get("OUTPUT_FORMAT") == "json"
    tz = ZoneInfo("Europe/Copenhagen")
    now = datetime.datetime.now(tz)
    if target_date is None:
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        day = target_date.replace(tzinfo=tz)

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

        summary = await build_daily_summary(
            client,
            prof,
            children,
            day,
            is_today=day.date() == now.date(),
            only_selected_children=bool(child),
            with_thread_messages=not is_json,
        )

    if is_json:
        if summary.widget_error is not None:
            print_error(f"preparing widget call: {summary.widget_error}")
        echo(to_json(daily_summary_json(summary, day, now)))
        return

    for line in format_report_intro_lines(
        f"Daily summary - {day.strftime('%A, %d %B %Y')}",
        [("Generated", now.strftime("%Y-%m-%d %H:%M"))],
    ):
        echo(line)
    echo()

    echo("Status")
    echo()
    for child_day in summary.children:
        _print_child_day(child_day)

    echo("Schedule")
    echo()
    for line in _event_slot_lines(summary.events) or ["No events today."]:
        echo(line)
    echo()

    if summary.widget_error is not None:
        print_error(f"preparing widget call: {summary.widget_error}")

    if summary.tasks_due:
        echo("Homework due today")
        echo()
        for task in summary.tasks_due:
            subjects = ", ".join(cls.subject_name for cls in task.classes if cls.subject_name)
            label = f"{subjects}: {task.title}" if subjects else task.title
            status = " ✓" if task.is_completed else ""
            echo(f"- {label}{status}")
        echo()

    _print_unread_threads(summary.unread)
