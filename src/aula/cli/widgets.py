import datetime
from collections import defaultdict
from collections.abc import Sequence
from zoneinfo import ZoneInfo

import click

from ..const import (
    EASYIQ_WEEKPLAN_WIDGETS,
    MIN_UDDANNELSE_TASK_WIDGETS,
    MIN_UDDANNELSE_UGEPLAN_WIDGETS,
    WIDGET_BIBLIOTEKET,
    WIDGET_DOCENDO,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_HUSKELISTEN,
    WIDGET_MEEBOOK,
)
from ..http import HttpRequestError
from ..models import (
    MUTask,
    Profile,
)
from ..utils.json import to_json
from ..utils.output import (
    danish_sort_key,
    echo,
    format_record_lines,
    output_json,
    print_empty,
    print_error,
    print_heading,
)
from ..utils.table import (
    card_width,
    print_text_card,
    print_wrapped_row_table,
)
from ..utils.week import weekday_index
from ..widgets import EasyIQChildNotInPortal, WidgetContext, easyiq_child_user_ids
from ._app import _get_client, async_cmd, cli
from ._helpers import (
    EASYIQ_ERRORS,
    _child_institution_filter,
    _docendo_plan_lines,
    _docendo_plans_for_child,
    _get_widget_context,
    _require_any_widget,
    _require_widget,
    _resolve_week,
    _with_child,
)


def _echo_no_easyiq_identity(child_name: str, resource: str, err: bool = False) -> None:
    """Say that a child has no EasyIQ plan, which is not a failure.

    EasyIQ's portal only knows children at institutions that use it. Daycare
    does not, so those children have no weekly plan or homework at all. This
    is printed rather than logged because a silent gap reads as a bug, and
    because the previous behaviour was to show them a sibling's plan
    (issue #68).
    """
    echo(f"No EasyIQ {resource} for {child_name}: EasyIQ has no record of this child.", err=err)


@cli.command("widgets")
@click.pass_context
@async_cmd
async def widgets(ctx):
    """List available widgets configured for the current user."""
    async with await _get_client(ctx) as client:
        try:
            widget_list = await client.get_widgets()
        except HttpRequestError as e:
            print_error(f"fetching widgets: {e}")
            return

        if output_json(ctx, [dict(w) for w in widget_list]):
            return

        if not widget_list:
            print_empty("widgets")
            return

        print_heading("Available widgets")

        for w in widget_list:
            for line in format_record_lines(
                title=w.name,
                properties=[
                    ("ID", w.widget_id),
                    ("Supplier", w.widget_supplier),
                    ("Type", w.widget_type),
                    ("Placement", w.placement),
                ],
            ):
                echo(line)
            echo()


# Min Uddannelse's internal task types; the portal itself labels a
# ``SimpelLektie`` simply as a homework note.
_MU_TASK_TYPE_LABELS = {"SimpelLektie": "Lektie"}


def _mu_task_classes(task: MUTask) -> str:
    """Format a task's classes, keeping the subject only when it adds something."""
    names = []
    for cls in task.classes:
        subject = cls.subject_name.strip()
        if subject and subject.lower() not in cls.name.lower():
            names.append(f"{cls.name} ({subject})")
        else:
            names.append(cls.name)
    return ", ".join(names)


def _mu_task_rows(tasks: Sequence[MUTask]) -> tuple[list[list[str]], list[str]]:
    """Build the table rows for one student's tasks plus the links they footnote."""
    links: list[str] = []
    rows = []
    previous_day = None
    for task in tasks:
        task_cell = task.title
        if task.deep_link:
            links.append(task.deep_link)
            task_cell = f"{task_cell} [{len(links)}]"
        if task.course:
            task_cell = f"{task_cell}\n  Course: {task.course.name}"
        rows.append(
            [
                # Repeating the day on every row of the same day is just noise.
                "" if task.weekday == previous_day else task.weekday,
                task_cell,
                _mu_task_classes(task),
                _MU_TASK_TYPE_LABELS.get(task.task_type, task.task_type),
                "✓" if task.is_completed else "",
            ]
        )
        previous_day = task.weekday
    return rows, links


def print_mu_task_tables(tasks: Sequence[MUTask]) -> None:
    """Print one day-ordered table per student, with task links as footnotes."""
    width = card_width()
    headers = ["Day", "Task", "Class", "Type", "Done"]
    by_student: dict[str, list[MUTask]] = defaultdict(list)
    for task in tasks:
        by_student[task.student_name].append(task)

    for position, student in enumerate(sorted(by_student, key=danish_sort_key)):
        student_tasks = sorted(
            by_student[student],
            key=lambda t: (weekday_index(t.weekday), t.due_date or datetime.datetime.max, t.title),
        )
        if position:
            echo()

        rows, links = _mu_task_rows(student_tasks)
        # A column every task leaves blank is noise, so drop it.
        keep = [i for i in range(len(headers)) if any(row[i].strip() for row in rows)]
        print_wrapped_row_table(
            [headers[i] for i in keep],
            [[row[i] for i in keep] for row in rows],
            title=student or "(unknown student)",
            width=width,
        )
        for number, link in enumerate(links, start=1):
            echo(f"  [{number}] {link}")


@cli.command("mu:opgaver")
@click.option(
    "--week",
    type=str,
    default=None,
    help="Week number (e.g. 8) or full format (2026-W8). Defaults to current week.",
)
@click.pass_context
@async_cmd
async def mu_opgaver(ctx, week):
    """Fetch Min Uddannelse tasks (opgaver) for children."""
    week = _resolve_week(week)
    async with await _get_client(ctx) as client:
        widget_id = await _require_any_widget(
            client, MIN_UDDANNELSE_TASK_WIDGETS, "MinUddannelse Opgaver"
        )
        if widget_id is None:
            return

        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        child_filter, institution_filter, session_uuid = widget_ctx

        try:
            opgaver = await client.widgets.get_mu_tasks(
                widget_id,
                child_filter,
                institution_filter,
                week,
                session_uuid,
            )
        except HttpRequestError as e:
            print_error(f"fetching tasks: {e}")
            return

        if output_json(ctx, [dict(t) for t in opgaver]):
            return

        print_heading(f"Min Uddannelse tasks [{week}]")

        if not opgaver:
            print_empty("tasks")
        else:
            echo()
            print_mu_task_tables(opgaver)


@cli.command("mu:ugeplan")
@click.option(
    "--week",
    type=str,
    default=None,
    help="Week number (e.g. 8) or full format (2026-W8). Defaults to current week.",
)
@click.pass_context
@async_cmd
async def mu_ugeplan(ctx, week):
    """Fetch Min Uddannelse weekly plans (ugebreve) for children."""
    week = _resolve_week(week)
    async with await _get_client(ctx) as client:
        widget_id = await _require_any_widget(
            client, MIN_UDDANNELSE_UGEPLAN_WIDGETS, "MinUddannelse Ugenoter"
        )
        if widget_id is None:
            return

        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        child_filter, institution_filter, session_uuid = widget_ctx

        from ..utils.html import html_to_blocks

        try:
            personer = await client.widgets.get_ugeplan(
                widget_id,
                child_filter,
                institution_filter,
                week,
                session_uuid,
            )
        except HttpRequestError as e:
            print_error(f"fetching weekly plans: {e}")
            return

        if output_json(ctx, [dict(p) for p in personer]):
            return

        if not personer:
            print_empty("weekly plans")
            return

        print_heading(f"Min Uddannelse weekly plans [{week}]")
        echo()

        width = card_width()
        rendered = 0
        for person in personer:
            for inst in person.institutions:
                for letter in inst.letters:
                    rendered += 1
                    print_text_card(
                        header_lines=[
                            f"{person.name} · {letter.group_name} · Week {letter.week_number}",
                            inst.name,
                        ],
                        body_blocks=html_to_blocks(letter.content_html),
                        width=width,
                        empty_body_text="(no weekly plan body)",
                    )
                    echo()

        if rendered == 0:
            print_empty("weekly plans")


@cli.command("easyiq:ugeplan")
@click.option(
    "--week",
    type=str,
    default=None,
    help="Week number (e.g. 8) or full format (2026-W8). Defaults to current week.",
)
@click.pass_context
@async_cmd
async def easyiq_ugeplan(ctx, week):
    """Fetch EasyIQ weekly plan (ugeplan) for children."""
    week = _resolve_week(week)
    async with await _get_client(ctx) as client:
        widget_id = await _require_any_widget(client, EASYIQ_WEEKPLAN_WIDGETS, "EasyIQ Ugeplan")
        if widget_id is None:
            return

        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        try:
            profile_context = await client.get_profile_context()
            _, institution_filter, session_uuid = WidgetContext.from_children(
                prof.children, profile_context
            )
        except (HttpRequestError, ValueError) as e:
            print_error(f"preparing widget call: {e}", err=ctx.obj.get("OUTPUT_FORMAT") == "json")
            return
        all_child_user_ids = easyiq_child_user_ids(profile_context)

        from ..utils.html import html_to_plain

        if ctx.obj.get("OUTPUT_FORMAT") == "json":
            all_appointments = []
            for child in prof.children:
                if not child.user_id:
                    continue
                child_id = child.user_id
                try:
                    appointments = await client.widgets.get_easyiq_weekplan(
                        week,
                        session_uuid,
                        _child_institution_filter(child, institution_filter),
                        child_id,
                        child_profile_id=str(child.id),
                        all_child_user_ids=all_child_user_ids,
                        all_institution_filter=institution_filter,
                        widget_id=widget_id,
                    )
                    all_appointments.extend(_with_child(dict(a), child) for a in appointments)
                except EasyIQChildNotInPortal:
                    _echo_no_easyiq_identity(child.name, "weekly plan", err=True)
                    continue
                except EASYIQ_ERRORS as e:
                    print_error(f"fetching EasyIQ weekplan for {child.name}: {e}", err=True)
                    continue
            echo(to_json(all_appointments))
            return

        print_heading(f"EasyIQ weekly plan [{week}]")
        rendered = 0

        for child in prof.children:
            if not child.user_id:
                continue
            child_id = child.user_id

            try:
                appointments = await client.widgets.get_easyiq_weekplan(
                    week,
                    session_uuid,
                    _child_institution_filter(child, institution_filter),
                    child_id,
                    child_profile_id=str(child.id),
                    all_child_user_ids=all_child_user_ids,
                    all_institution_filter=institution_filter,
                    widget_id=widget_id,
                )
            except EasyIQChildNotInPortal:
                _echo_no_easyiq_identity(child.name, "weekly plan")
                continue
            except EASYIQ_ERRORS as e:
                print_error(f"fetching EasyIQ weekplan for {child.name}: {e}")
                continue

            for appt in appointments:
                rendered += 1
                for line in format_record_lines(
                    title=appt.title,
                    properties=[
                        ("Child", child.name),
                        ("Class", appt.activities),
                        ("Start", appt.start),
                        ("End", appt.end),
                    ],
                    body_lines=html_to_plain(appt.description).splitlines()
                    if appt.description
                    else [],
                    body_label="Body",
                    empty_body_text="(no description)",
                ):
                    echo(line)
                echo()

        if rendered == 0:
            print_empty("appointments")


@cli.command("easyiq:homework")
@click.option(
    "--week",
    type=str,
    default=None,
    help="Week number (e.g. 8) or full format (2026-W8). Defaults to current week.",
)
@click.pass_context
@async_cmd
async def easyiq_homework(ctx, week):
    """Fetch EasyIQ homework assignments for children."""
    week = _resolve_week(week)
    async with await _get_client(ctx) as client:
        if not await _require_widget(client, WIDGET_EASYIQ_HOMEWORK, "EasyIQ Lektier"):
            return

        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        try:
            profile_context = await client.get_profile_context()
            _, institution_filter, session_uuid = WidgetContext.from_children(
                prof.children, profile_context
            )
        except (HttpRequestError, ValueError) as e:
            print_error(f"preparing widget call: {e}", err=ctx.obj.get("OUTPUT_FORMAT") == "json")
            return
        all_child_user_ids = easyiq_child_user_ids(profile_context)

        from ..utils.html import html_to_plain

        if ctx.obj.get("OUTPUT_FORMAT") == "json":
            all_homework = []
            for child in prof.children:
                if not child.user_id:
                    continue
                child_id = child.user_id
                try:
                    homework = await client.widgets.get_easyiq_homework(
                        week,
                        session_uuid,
                        _child_institution_filter(child, institution_filter),
                        child_id,
                        child_profile_id=str(child.id),
                        all_child_user_ids=all_child_user_ids,
                        all_institution_filter=institution_filter,
                    )
                    all_homework.extend(_with_child(dict(hw), child) for hw in homework)
                except EasyIQChildNotInPortal:
                    _echo_no_easyiq_identity(child.name, "homework", err=True)
                    continue
                except EASYIQ_ERRORS as e:
                    print_error(f"fetching EasyIQ homework for {child.name}: {e}", err=True)
                    continue
            echo(to_json(all_homework))
            return

        print_heading(f"EasyIQ homework [{week}]")
        rendered = 0

        for child in prof.children:
            if not child.user_id:
                continue
            child_id = child.user_id

            try:
                homework = await client.widgets.get_easyiq_homework(
                    week,
                    session_uuid,
                    _child_institution_filter(child, institution_filter),
                    child_id,
                    child_profile_id=str(child.id),
                    all_child_user_ids=all_child_user_ids,
                    all_institution_filter=institution_filter,
                )
            except EasyIQChildNotInPortal:
                _echo_no_easyiq_identity(child.name, "homework")
                continue
            except EASYIQ_ERRORS as e:
                print_error(f"fetching EasyIQ homework for {child.name}: {e}")
                continue

            for hw in homework:
                rendered += 1
                status = "Completed" if hw.is_completed else "Pending"
                for line in format_record_lines(
                    title=hw.title,
                    properties=[
                        ("Child", child.name),
                        ("Class", hw.activities),
                        ("Status", status),
                        ("Subject", hw.subject),
                        ("Due", hw.due_date),
                    ],
                    body_lines=html_to_plain(hw.description).splitlines() if hw.description else [],
                    body_label="Body",
                    empty_body_text="(no description)",
                ):
                    echo(line)
                echo()

        if rendered == 0:
            print_empty("homework")


@cli.command("meebook:ugeplan")
@click.option(
    "--week",
    type=str,
    default=None,
    help="Week number (e.g. 8) or full format (2026-W8). Defaults to current week.",
)
@click.pass_context
@async_cmd
async def meebook_ugeplan(ctx, week):
    """Fetch Meebook weekly plan (ugeplan) for children."""
    week = _resolve_week(week)
    async with await _get_client(ctx) as client:
        if not await _require_widget(client, WIDGET_MEEBOOK, "Meebook"):
            return

        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        child_filter, institution_filter, session_uuid = widget_ctx

        try:
            students = await client.widgets.get_meebook_weekplan(
                child_filter, institution_filter, week, session_uuid
            )
        except HttpRequestError as e:
            print_error(f"fetching Meebook weekplan: {e}")
            return

        if output_json(ctx, [dict(s) for s in students]):
            return

        if not students:
            print_empty("weekly plans")
            return

        from ..utils.html import html_to_plain

        print_heading(f"Meebook weekly plan [{week}]")
        rendered = 0

        for student in students:
            for day in student.week_plan:
                if not day.tasks:
                    continue
                for task in day.tasks:
                    rendered += 1
                    label = task.title or task.type
                    if task.pill:
                        label = f"[{task.pill}] {label}"
                    for line in format_record_lines(
                        title=label,
                        properties=[("Student", student.name), ("Date", day.date)],
                        body_lines=html_to_plain(task.content).splitlines() if task.content else [],
                        body_label="Body",
                        empty_body_text="(no description)",
                    ):
                        echo(line)
                    echo()

        if rendered == 0:
            print_empty("weekly plans")


@cli.command("docendo:ugeplan")
@click.option(
    "--week",
    type=str,
    default=None,
    help="Week number (e.g. 8) or full format (2026-W8). Defaults to current week.",
)
@click.pass_context
@async_cmd
async def docendo_ugeplan(ctx, week):
    """Fetch Docendo weekly plans (ugeplan) for children."""
    week = _resolve_week(week)
    async with await _get_client(ctx) as client:
        if not await _require_widget(client, WIDGET_DOCENDO, "Docendo"):
            return

        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        try:
            plans = await client.widgets.get_docendo_weekplan(week)
        except HttpRequestError as e:
            print_error(f"fetching Docendo weekplan: {e}")
            return

        only_child = len(prof.children) == 1
        pairs = [
            (child, plan)
            for child in prof.children
            for plan in _docendo_plans_for_child(plans, child, only_child=only_child)
        ]
        unmatched = [plan for plan in plans if all(plan is not p for _, p in pairs)]

        rows = [_with_child(dict(plan), child) for child, plan in pairs]
        rows += [{**dict(plan), "child_id": None, "child_name": None} for plan in unmatched]
        if output_json(ctx, rows):
            return

        if not plans:
            print_empty("weekly plans")
            return

        print_heading(f"Docendo weekly plan [{week}]")
        sections = [(f"{child.name} ({plan.name})", plan) for child, plan in pairs]
        sections += [(f"{plan.name} (no matching child)", plan) for plan in unmatched]
        for title, plan in sections:
            echo(title)
            for line in _docendo_plan_lines(plan):
                echo(f"  {line}")
            echo()


@cli.command("momo:forløb")
@click.pass_context
@async_cmd
async def momo_course(ctx):
    """Fetch MoMo courses (forløb) for children."""
    async with await _get_client(ctx) as client:
        if not await _require_widget(client, WIDGET_HUSKELISTEN, "Huskelisten"):
            return

        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        children, institutions, session_uuid = widget_ctx

        try:
            users_with_courses = await client.widgets.get_momo_courses(
                children, institutions, session_uuid
            )
        except HttpRequestError as e:
            print_error(f"fetching MoMo courses: {e}")
            return

        if output_json(ctx, [dict(u) for u in users_with_courses]):
            return

        if not users_with_courses:
            print_empty("courses")
            return

        print_heading("MoMo courses")
        rendered = 0

        for user in users_with_courses:
            name = user.name.split()[0] if user.name else "Unknown"
            for course in user.courses:
                rendered += 1
                for line in format_record_lines(
                    title=course.title,
                    properties=[("Child", name)],
                ):
                    echo(line)
                echo()

        if rendered == 0:
            print_empty("courses")


@cli.command("momo:huskeliste")
@click.pass_context
@async_cmd
async def momo_reminders(ctx):
    """Fetch MoMo reminders (huskelisten) for children."""
    async with await _get_client(ctx) as client:
        if not await _require_widget(client, WIDGET_HUSKELISTEN, "Huskelisten"):
            return

        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        children, institutions, session_uuid = widget_ctx

        today = datetime.date.today()
        from_date = today.isoformat()
        due_no_later_than = (today + datetime.timedelta(days=7)).isoformat()

        try:
            users = await client.widgets.get_momo_reminders(
                children, institutions, session_uuid, from_date, due_no_later_than
            )
        except HttpRequestError as e:
            print_error(f"fetching reminders: {e}")
            return

        if output_json(ctx, [dict(u) for u in users]):
            return

        if not users:
            print_empty("reminders")
            return

        tz = ZoneInfo("Europe/Copenhagen")
        print_heading("MoMo reminders")
        rendered = 0
        for user in users:
            name = user.user_name.split()[0] if user.user_name else "Unknown"

            for r in user.team_reminders:
                due = ""
                if r.due_date:
                    try:
                        dt = datetime.datetime.fromisoformat(
                            r.due_date.replace("Z", "+00:00")
                        ).astimezone(tz)
                        due = dt.strftime("%A %d. %B")
                    except ValueError:
                        due = r.due_date
                rendered += 1
                for line in format_record_lines(
                    title=r.subject_name or "Team reminder",
                    properties=[
                        ("Child", name),
                        ("Due", due),
                        ("Created by", r.created_by),
                        ("Team", r.team_name),
                    ],
                    body_lines=[r.reminder_text],
                    body_label="Body",
                    empty_body_text="(no reminder text)",
                ):
                    echo(line)
                echo()

            for r in user.assignment_reminders:
                due = ""
                if r.due_date:
                    try:
                        dt = datetime.datetime.fromisoformat(
                            r.due_date.replace("Z", "+00:00")
                        ).astimezone(tz)
                        due = dt.strftime("%A %d. %B")
                    except ValueError:
                        due = r.due_date
                teams = ", ".join(r.team_names) if r.team_names else ""
                rendered += 1
                for line in format_record_lines(
                    title="Assignment reminder",
                    properties=[("Child", name), ("Due", due), ("Teams", teams)],
                    body_lines=[r.assignment_text],
                    body_label="Body",
                    empty_body_text="(no assignment text)",
                ):
                    echo(line)
                echo()

        if rendered == 0:
            print_empty("reminders")


@cli.command("library:status")
@click.pass_context
@async_cmd
async def library_status(ctx):
    """Fetch library loans and reservations for children."""
    async with await _get_client(ctx) as client:
        if not await _require_widget(client, WIDGET_BIBLIOTEKET, "Biblioteket"):
            return

        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        children, institutions, session_uuid = widget_ctx

        try:
            status = await client.widgets.get_library_status(
                WIDGET_BIBLIOTEKET,
                children,
                institutions,
                session_uuid,
            )
        except HttpRequestError as e:
            print_error(f"fetching library status: {e}")
            return

        if output_json(ctx, dict(status)):
            return

        print_heading("Library status")
        rendered = 0

        for loan in status.loans:
            rendered += 1
            for line in format_record_lines(
                title=loan.title,
                properties=[
                    ("Category", "Loan"),
                    ("Author", loan.author),
                    ("Borrower", loan.patron_display_name),
                    ("Due", loan.due_date),
                ],
            ):
                echo(line)
            echo()

        for loan in status.longterm_loans:
            rendered += 1
            for line in format_record_lines(
                title=loan.title,
                properties=[
                    ("Category", "Long-term loan"),
                    ("Author", loan.author),
                    ("Borrower", loan.patron_display_name),
                    ("Due", loan.due_date),
                ],
            ):
                echo(line)
            echo()

        for reservation in status.reservations:
            rendered += 1
            for line in format_record_lines(
                title=str(reservation),
                properties=[("Category", "Reservation")],
            ):
                echo(line)
            echo()

        if rendered == 0:
            print_empty("loans or reservations")
