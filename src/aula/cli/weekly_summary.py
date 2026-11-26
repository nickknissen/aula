import datetime
import enum
from zoneinfo import ZoneInfo

import click

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
from ..widgets import EasyIQChildNotInPortal, easyiq_child_user_ids
from ._app import _get_client, async_cmd, cli
from ._helpers import (
    _child_institution_filter,
    _docendo_plan_lines,
    _docendo_plans_for_child,
    _first_available_widget,
    _get_widget_context,
    _has_widget,
    _resolve_week,
    _thread_meta,
    _unique_names,
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
    from ..utils.html import html_to_plain

    is_json = ctx.obj.get("OUTPUT_FORMAT") == "json"
    week = _resolve_week(week)

    # ── Provider resolution ──────────────────────────────────────────────────
    if providers:
        enabled: set[WeeklySummaryProvider] = (
            set(WeeklySummaryProvider)
            if "all" in providers
            else {WeeklySummaryProvider(p) for p in providers}
        )
    else:
        cfg = load_config().get("weekly_summary") or {}
        enabled = set()
        for key, active in cfg.items():
            try:
                provider = WeeklySummaryProvider(key)
            except ValueError:
                _LOGGER.warning("Unknown weekly_summary provider in config: %r (ignored)", key)
                continue
            if active:
                enabled.add(provider)

    year_num, week_num = week.split("-W")
    week_start = datetime.datetime.fromisocalendar(int(year_num), int(week_num), 1).replace(
        tzinfo=ZoneInfo("Europe/Copenhagen")
    )
    week_end = datetime.datetime.fromisocalendar(int(year_num), int(week_num), 5).replace(
        tzinfo=ZoneInfo("Europe/Copenhagen"), hour=23, minute=59, second=59
    )

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        # Filter children by name if --child provided
        children = prof.children
        if child:
            needle = child.lower()
            children = [c for c in prof.children if needle in c.name.lower()]
            if not children:
                names = ", ".join(c.name for c in prof.children)
                print_error(f"no child matching '{child}'. Available: {names}")
                return

        now = datetime.datetime.now(ZoneInfo("Europe/Copenhagen"))
        json_result: dict | None = {"week": week, "generated": now.isoformat()} if is_json else None

        if not is_json:
            for line in format_report_intro_lines(
                f"Weekly overview - week {week_num}, {year_num}",
                [
                    ("Generated", now.strftime("%Y-%m-%d")),
                    (
                        "Period",
                        f"{week_start.strftime('%a %d %b')} - {week_end.strftime('%a %d %b %Y')}",
                    ),
                ],
            ):
                echo(line)
            echo()

        # ── Calendar events ──────────────────────────────────────────────────
        child_inst_ids = [c.id for c in children]
        try:
            events = await client.get_calendar_events(child_inst_ids, week_start, week_end)
        except Exception as e:
            events = []
            _LOGGER.warning("Could not fetch calendar events: %s", e)

        if json_result is not None:
            json_result["calendar_events"] = [dict(ev) for ev in events]

        if not is_json:
            echo("Calendar events")
            echo()
        if not is_json:
            if events:
                # Group by date
                from collections import defaultdict

                by_day: dict[datetime.date, list] = defaultdict(list)
                for ev in events:
                    by_day[ev.start_datetime.date()].append(ev)

                for day_offset in range(5):
                    day = (week_start + datetime.timedelta(days=day_offset)).date()
                    day_label = (week_start + datetime.timedelta(days=day_offset)).strftime(
                        "%A, %d %B"
                    )
                    day_events = sorted(by_day.get(day, []), key=lambda e: e.start_datetime)
                    echo(day_label)
                    if day_events:
                        # Merge events that share the exact same timeslot
                        slots: dict[tuple, list] = defaultdict(list)
                        for ev in day_events:
                            slots[(ev.start_datetime, ev.end_datetime)].append(ev)
                        for (start_dt, end_dt), evs in sorted(slots.items()):
                            time_range = f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
                            titles = " / ".join(dict.fromkeys(ev.title or "Untitled" for ev in evs))
                            locations = list(
                                dict.fromkeys(ev.location for ev in evs if ev.location)
                            )
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
                        echo("- (no events)")
                    echo()
            else:
                print_empty("calendar events")
                echo()

        # ── Unread messages ──────────────────────────────────────────────────
        try:
            unread_threads = await client.get_message_threads(filter_on="unread")
        except Exception as e:
            unread_threads = []
            _LOGGER.warning("Could not fetch unread messages: %s", e)

        if json_result is not None:
            json_result["unread_messages"] = [dict(t) for t in unread_threads]

        if not is_json and unread_threads:
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

        if not enabled:
            if json_result is not None:
                echo(to_json(json_result))
            return  # nothing to fetch beyond calendar

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            if json_result is not None:
                echo(to_json(json_result))
                return
            echo("(Widget context unavailable – skipping provider data)")
            return

        child_filter, institution_filter, session_uuid = widget_ctx

        try:
            all_child_user_ids = easyiq_child_user_ids(await client.get_profile_context())
        except Exception as e:
            _LOGGER.warning("Could not read children for the EasyIQ child filter: %s", e)
            all_child_user_ids = []

        # Filter child_filter to selected children only
        if child:
            selected_user_ids = {c.user_id for c in children if c.user_id}
            child_filter = [uid for uid in child_filter if uid in selected_user_ids]

        # ── Min Uddannelse – Homework & Tasks ────────────────────────────────
        mu_task_widget = (
            await _first_available_widget(client, MIN_UDDANNELSE_TASK_WIDGETS)
            if WeeklySummaryProvider.MU_OPGAVER in enabled
            else None
        )
        if mu_task_widget is not None:
            try:
                tasks = await client.widgets.get_mu_tasks(
                    mu_task_widget,
                    child_filter,
                    institution_filter,
                    week,
                    session_uuid,
                )
            except Exception as e:
                tasks = []
                _LOGGER.warning("Could not fetch MU tasks: %s", e)

            if json_result is not None:
                json_result["mu_tasks"] = [dict(t) for t in tasks]

            if not is_json:
                echo("Homework & tasks (Min Uddannelse)")
                echo()
                if tasks:
                    for task in tasks:
                        parts = []
                        if task.weekday:
                            parts.append(task.weekday)
                        subjects = ", ".join(
                            cls.subject_name for cls in task.classes if cls.subject_name
                        )
                        if subjects:
                            parts.append(subjects)
                        label = f"{' – '.join(parts)}: {task.title}" if parts else task.title
                        status = " ✓" if task.is_completed else ""
                        echo(f"- {label}{status}")
                        if task.task_type:
                            echo(f"  Type: {task.task_type}")
                else:
                    print_empty("tasks")
                echo()

        # ── Min Uddannelse – Weekly Letter (Ugeplan) ─────────────────────────
        mu_ugeplan_widget = (
            await _first_available_widget(client, MIN_UDDANNELSE_UGEPLAN_WIDGETS)
            if WeeklySummaryProvider.MU_UGEPLAN in enabled
            else None
        )
        if mu_ugeplan_widget is not None:
            try:
                mu_persons = await client.widgets.get_ugeplan(
                    mu_ugeplan_widget,
                    child_filter,
                    institution_filter,
                    week,
                    session_uuid,
                )
            except Exception as e:
                mu_persons = []
                _LOGGER.warning("Could not fetch MU ugeplan: %s", e)

            if json_result is not None:
                json_result["mu_ugeplan"] = [dict(p) for p in mu_persons]

            if not is_json and mu_persons:
                echo("Weekly letter (Min Uddannelse ugeplan)")
                echo()
                for person in mu_persons:
                    for inst in person.institutions:
                        for letter in inst.letters:
                            echo(f"{person.name} - {letter.group_name} ({inst.name})")
                            echo()
                            for line in html_to_plain(letter.content_html).splitlines():
                                echo(line)
                            echo()

        # ── Meebook – Weekly Plan ────────────────────────────────────────────
        if WeeklySummaryProvider.MEEBOOK in enabled and await _has_widget(client, WIDGET_MEEBOOK):
            try:
                meebook_students = await client.widgets.get_meebook_weekplan(
                    child_filter, institution_filter, week, session_uuid
                )
            except Exception as e:
                meebook_students = []
                _LOGGER.warning("Could not fetch Meebook weekplan: %s", e)

            if json_result is not None:
                json_result["meebook_weekplan"] = [dict(s) for s in meebook_students]

            if not is_json and meebook_students:
                echo("Weekly plan (Meebook)")
                echo()
                for student in meebook_students:
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
                            if task.content:
                                for line in html_to_plain(task.content).splitlines():
                                    if line.strip():
                                        echo(f"  {line}")
                    echo()

        # ── Docendo – Weekly Plan ────────────────────────────────────────────
        if WeeklySummaryProvider.DOCENDO in enabled and await _has_widget(client, WIDGET_DOCENDO):
            try:
                docendo_plans = await client.widgets.get_docendo_weekplan(week)
            except Exception as e:
                docendo_plans = []
                _LOGGER.warning("Could not fetch Docendo weekplan: %s", e)

            only_child = len(prof.children) == 1
            docendo_pairs = [
                (c, plan)
                for c in children
                for plan in _docendo_plans_for_child(docendo_plans, c, only_child=only_child)
            ]

            if json_result is not None:
                json_result["docendo_weekplan"] = [
                    _with_child(dict(plan), c) for c, plan in docendo_pairs
                ]

            if not is_json and docendo_pairs:
                echo("Weekly plan (Docendo)")
                echo()
                for c, plan in docendo_pairs:
                    echo(f"{c.name} ({plan.name})")
                    echo()
                    for line in _docendo_plan_lines(plan):
                        echo(line)
                    echo()

        # ── EasyIQ – Weekly Plan ─────────────────────────────────────────────
        easyiq_weekplan_widget = (
            await _first_available_widget(client, EASYIQ_WEEKPLAN_WIDGETS)
            if WeeklySummaryProvider.EASYIQ in enabled
            else None
        )
        if easyiq_weekplan_widget is not None:
            easyiq_appointments: list[dict] = []
            easyiq_any = False
            for c in children:
                if not c.user_id:
                    continue
                c_user_id = c.user_id

                try:
                    appointments = await client.widgets.get_easyiq_weekplan(
                        week,
                        session_uuid,
                        _child_institution_filter(c, institution_filter),
                        c_user_id,
                        child_profile_id=str(c.id),
                        all_child_user_ids=all_child_user_ids,
                        all_institution_filter=institution_filter,
                        widget_id=easyiq_weekplan_widget,
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

                if not appointments:
                    continue

                easyiq_appointments.extend(_with_child(dict(a), c) for a in appointments)

                if not is_json:
                    if not easyiq_any:
                        echo("Weekly plan (EasyIQ)")
                        echo()
                        easyiq_any = True

                    echo(c.name)
                    echo()
                    for appt in appointments:
                        echo(f"- {appt.title}")
                        if appt.start or appt.end:
                            echo(f"  {appt.start} – {appt.end}")
                        if appt.description:
                            for line in html_to_plain(appt.description).splitlines():
                                if line.strip():
                                    echo(f"  {line}")
                    echo()

            if json_result is not None:
                json_result["easyiq_weekplan"] = easyiq_appointments

        # ── EasyIQ – Homework ──────────────────────────────────────────────────
        if WeeklySummaryProvider.EASYIQ_HOMEWORK in enabled and await _has_widget(
            client, WIDGET_EASYIQ_HOMEWORK
        ):
            easyiq_hw_items: list[dict] = []
            easyiq_hw_any = False
            for c in children:
                if not c.user_id:
                    continue
                c_user_id = c.user_id

                try:
                    homework = await client.widgets.get_easyiq_homework(
                        week,
                        session_uuid,
                        _child_institution_filter(c, institution_filter),
                        c_user_id,
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

                if not homework:
                    continue

                easyiq_hw_items.extend(_with_child(dict(hw), c) for hw in homework)

                if not is_json:
                    if not easyiq_hw_any:
                        echo("Homework (EasyIQ)")
                        echo()
                        easyiq_hw_any = True

                    echo(c.name)
                    echo()
                    for hw in homework:
                        status = "[x]" if hw.is_completed else "[ ]"
                        echo(f"- {status} {hw.title}")
                        if hw.subject:
                            echo(f"  Subject: {hw.subject}")
                        if hw.due_date:
                            echo(f"  Due: {hw.due_date}")
                        if hw.description:
                            for line in html_to_plain(hw.description).splitlines():
                                if line.strip():
                                    echo(f"  {line}")
                    echo()

            if json_result is not None:
                json_result["easyiq_homework"] = easyiq_hw_items

        if json_result is not None:
            echo(to_json(json_result))
