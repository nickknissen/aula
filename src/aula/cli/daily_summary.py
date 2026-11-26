import datetime
from zoneinfo import ZoneInfo

import click

from ..const import (
    MIN_UDDANNELSE_TASK_WIDGETS,
)
from ..models import (
    Profile,
)
from ..utils.diagnostics import credential_logger
from ..utils.html import strip_control_chars
from ..utils.json import to_json
from ..utils.mapping import get_in
from ..utils.output import (
    echo,
    format_report_intro_lines,
    print_empty,
    print_error,
)
from ..utils.week import DANISH_WEEKDAYS
from ._app import _get_client, async_cmd, cli
from ._helpers import _first_available_widget, _get_widget_context, _thread_meta, _unique_names

_LOGGER = credential_logger(__name__)


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
    from collections import defaultdict

    is_json = ctx.obj.get("OUTPUT_FORMAT") == "json"
    tz = ZoneInfo("Europe/Copenhagen")
    now = datetime.datetime.now(tz)

    if target_date is None:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        today = target_date.replace(tzinfo=tz)

    day_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = today.replace(hour=23, minute=59, second=59, microsecond=0)

    iso = today.isocalendar()
    week = f"{iso[0]}-W{iso[1]}"
    today_weekday_da = DANISH_WEEKDAYS[today.weekday()]
    day_label = today.strftime("%A, %d %B %Y")

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        children = prof.children
        if child:
            needle = child.lower()
            children = [c for c in prof.children if needle in c.name.lower()]
            if not children:
                names = ", ".join(c.name for c in prof.children)
                print_error(f"no child matching '{child}'. Available: {names}")
                return

        json_result: dict | None = (
            {"date": today.date().isoformat(), "generated": now.isoformat()} if is_json else None
        )

        if not is_json:
            for line in format_report_intro_lines(
                f"Daily summary - {day_label}",
                [("Generated", now.strftime("%Y-%m-%d %H:%M"))],
            ):
                echo(line)
            echo()

        # ── Presence templates for target date (planned times) ────────────────
        # Extract institution profile IDs from children (Child.id, not profile_id)
        child_institution_profile_ids = [c.id for c in children]
        try:
            presence_tmpl_list = await client.get_presence_templates(
                child_institution_profile_ids, today.date(), today.date()
            )
        except Exception as e:
            presence_tmpl_list = []
            _LOGGER.warning("Could not fetch presence templates: %s", e)

        from ..models import DayTemplate

        # Log ID mapping for verification (debug only)
        _LOGGER.debug("=== ID MAPPING VERIFICATION ===")
        _LOGGER.debug("Children and their IDs:")
        for c in children:
            _LOGGER.debug("  Child: %s | id=%s | profile_id=%s", c.name, c.id, c.profile_id)
        _LOGGER.debug("Presence templates and their institution profile IDs:")
        for tmpl in presence_tmpl_list:
            if tmpl.institution_profile:
                _LOGGER.debug(
                    "  Template: %s | id=%s | profile_id=%s",
                    tmpl.institution_profile.name or "unknown",
                    tmpl.institution_profile.id,
                    tmpl.institution_profile.profile_id,
                )
        _LOGGER.debug("=== END ID MAPPING VERIFICATION ===")

        # Find day template matching target date
        target_date_str = today.date().isoformat()
        day_template_by_child: dict[int, DayTemplate] = {}
        for tmpl in presence_tmpl_list:
            if not tmpl.institution_profile:
                _LOGGER.warning("Presence template has no institution profile, skipping")
                continue
            if not tmpl.day_templates:
                _LOGGER.warning(
                    "Presence template for %s has no day templates",
                    tmpl.institution_profile.name if tmpl.institution_profile else "unknown",
                )
                continue
            # Filter to find the template matching the target date
            matching = [d for d in tmpl.day_templates if d.by_date == target_date_str]
            if matching:
                profile_id = tmpl.institution_profile.id
                if profile_id is not None:
                    day_template_by_child[profile_id] = matching[0]

        # Daily overview only reflects today's actual state — skip for other dates
        is_today = today.date() == now.date()

        # ── Check-in status ───────────────────────────────────────────────────
        if not is_json:
            echo("Status")
            echo()

        overview_data = []
        for c in children:
            day_tmpl = day_template_by_child.get(c.id)

            ov = None
            if is_today:
                try:
                    ov = await client.get_daily_overview(c.id)
                except Exception as e:
                    _LOGGER.warning("Could not fetch daily overview for %s: %s", c.name, e)

            if is_json:
                entry = {"child": dict(c)}
                if ov is not None:
                    entry["overview"] = dict(ov)
                if day_tmpl:
                    entry["presence_template"] = dict(day_tmpl)
                overview_data.append(entry)
                continue

            echo(c.name)

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

        if json_result is not None:
            json_result["status"] = overview_data

        # ── Schedule ──────────────────────────────────────────────────────────
        try:
            events = await client.get_calendar_events(
                child_institution_profile_ids, day_start, day_end
            )
        except Exception as e:
            events = []
            _LOGGER.warning("Could not fetch calendar events: %s", e)

        if json_result is not None:
            json_result["calendar_events"] = [dict(ev) for ev in events]

        if not is_json:
            echo("Schedule")
            echo()
            if events:
                slots: dict[tuple, list] = defaultdict(list)
                for ev in sorted(events, key=lambda e: e.start_datetime):
                    slots[(ev.start_datetime, ev.end_datetime)].append(ev)
                for (start_dt, end_dt), evs in sorted(slots.items()):
                    time_range = f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
                    titles = " / ".join(dict.fromkeys(ev.title or "Untitled" for ev in evs))
                    locations = list(dict.fromkeys(ev.location for ev in evs if ev.location))
                    teachers = _unique_names(ev.teacher_names for ev in evs)
                    substitutes = _unique_names(
                        ev.substitute_names for ev in evs if ev.has_substitute
                    )
                    parts = [time_range, titles]
                    if locations:
                        parts.append(f"({' / '.join(locations)})")
                    if teachers:
                        parts.append(f"[{' / '.join(teachers)}]")
                    if substitutes:
                        parts.append(f"[Substitute: {' / '.join(substitutes)}]")
                    echo(f"- {'  '.join(parts)}")
            else:
                echo("No events today.")
            echo()

        # ── Homework due today ────────────────────────────────────────────────
        today_tasks: list = []
        widget_ctx = await _get_widget_context(client, prof)
        mu_task_widget = await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS)
        if widget_ctx is not None and mu_task_widget is not None:
            child_filter, institution_filter, session_uuid = widget_ctx

            if child:
                selected_user_ids = {c.user_id for c in children if c.user_id}
                child_filter = [uid for uid in child_filter if uid in selected_user_ids]

            try:
                all_tasks = await client.widgets.get_mu_tasks(
                    mu_task_widget,
                    child_filter,
                    institution_filter,
                    week,
                    session_uuid,
                )
            except Exception as e:
                all_tasks = []
                _LOGGER.warning("Could not fetch tasks: %s", e)

            today_tasks = [
                t
                for t in all_tasks
                if t.weekday == today_weekday_da
                or (t.due_date and t.due_date.date() == today.date())
            ]

        if json_result is not None:
            json_result["homework_due_today"] = [dict(t) for t in today_tasks]

        if not is_json and today_tasks:
            echo("Homework due today")
            echo()
            for task in today_tasks:
                subjects = ", ".join(cls.subject_name for cls in task.classes if cls.subject_name)
                label = f"{subjects}: {task.title}" if subjects else task.title
                status = " ✓" if task.is_completed else ""
                echo(f"- {label}{status}")
            echo()

        # ── Unread messages ───────────────────────────────────────────────────
        try:
            unread_threads = await client.get_message_threads(filter_on="unread")
        except Exception as e:
            unread_threads = []
            _LOGGER.warning("Could not fetch unread messages: %s", e)

        if json_result is not None:
            json_result["unread_messages"] = [dict(t) for t in unread_threads]
            echo(to_json(json_result))
            return

        if unread_threads:
            echo("Unread messages")
            echo()
            for thread in unread_threads:
                echo(strip_control_chars(thread.subject))
                if meta := _thread_meta(thread):
                    echo(f"  Meta: {strip_control_chars(meta)}")
                echo()
                try:
                    msgs = await client.get_messages_for_thread(thread.thread_id)
                    for msg in msgs:
                        msg_raw = msg._raw or {}
                        sender = get_in(msg_raw, "sender.fullName", default="Unknown")
                        send_date = msg_raw.get("sendDateTime", "")
                        echo(f"Author: {sender}")
                        if send_date:
                            echo(f"Date: {send_date}")
                        for line in msg.content.splitlines():
                            if line.strip():
                                echo(line)
                        echo()
                except Exception as e:
                    _LOGGER.warning(
                        "Could not fetch messages for thread %s: %s", thread.thread_id, e
                    )
                    echo()
