#!/usr/bin/env python3
import asyncio
import datetime
import enum
import functools
import logging
import os
import sys
from zoneinfo import ZoneInfo

import click
import qrcode

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv is an optional dependency

# On Windows, use SelectorEventLoopPolicy to avoid 'Event loop closed' issues
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from .api_client import AulaApiClient
from .auth_flow import authenticate_and_create_client
from .config import CONFIG_FILE, DEFAULT_TOKEN_FILE, load_config, save_config
from .models import DailyOverview, Message, MessageThread, Profile
from .token_storage import FileTokenStorage


# Decorator to run async functions within Click commands
def async_cmd(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


class WeeklySummaryProvider(str, enum.Enum):
    MU_OPGAVER = "mu_opgaver"
    MU_UGEPLAN = "mu_ugeplan"
    MEEBOOK = "meebook"
    EASYIQ = "easyiq"


def get_mitid_username(ctx: click.Context) -> str:
    """Get MitID username from context, environment, config, or prompt."""
    # First try context (command line)
    username = ctx.obj.get("MITID_USERNAME")

    # Then try environment variable
    if not username:
        username = os.getenv("AULA_MITID_USERNAME")

    # Then try config file
    if not username:
        config = load_config()
        username = config.get("mitid_username")

    # Finally, prompt if still missing
    if not username:
        click.echo("MitID authentication required")
        username = click.prompt("MitID username")

        if click.confirm("Save MitID username to config file?"):
            config = load_config()
            config["mitid_username"] = username
            save_config(config)
            click.echo(f"Username saved to {CONFIG_FILE}")

    return username


# Define the main group
@click.group()
@click.option(
    "--username",
    help="MitID username (can also be set via AULA_MITID_USERNAME env var or config file)",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity: -v for INFO, -vv for DEBUG.",
)
@click.pass_context
def cli(ctx, username: str | None, verbose: int):
    """CLI for interacting with Aula API"""
    # Configure logging based on verbosity
    log_level = logging.WARNING  # Default: Show warnings and above
    if verbose == 1:
        log_level = logging.INFO  # -v: Show info and above
    elif verbose >= 2:
        log_level = logging.DEBUG  # -vv, -vvv, etc.: Show debug and above

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
        force=True,  # Ensures reconfiguration even if root handlers exist
    )

    # Set library loggers to a less verbose level to reduce noise
    if log_level < logging.WARNING:
        for lib_name in ["httpx", "httpcore", "asyncio"]:
            logging.getLogger(lib_name).setLevel(logging.WARNING)

    # Initialize context
    ctx.ensure_object(dict)

    if username:
        ctx.obj["MITID_USERNAME"] = username


def _print_qr_codes_in_terminal(qr1: qrcode.QRCode, qr2: qrcode.QRCode) -> None:
    """Print QR codes as ASCII art in the terminal."""
    click.echo("=" * 60)
    click.echo("SCAN THESE QR CODES WITH YOUR MITID APP")
    click.echo("=" * 60)
    click.echo("QR CODE 1 (Scan this first):")
    try:
        qr1.print_ascii(invert=True)
    except UnicodeEncodeError:
        qr1.print_tty()

    click.echo("QR CODE 2 (Scan this second):")
    try:
        qr2.print_ascii(invert=True)
    except UnicodeEncodeError:
        qr2.print_tty()

    click.echo("=" * 60)
    click.echo("Waiting for you to scan the QR codes...")
    click.echo("=" * 60)


def _resolve_week(week: str | None) -> str:
    """Resolve a week argument to YYYY-Wn format.

    Accepts None (current week), a bare number like '8', or full 'YYYY-Wn'.
    """
    now = datetime.datetime.now(ZoneInfo("Europe/Copenhagen"))
    if week is None:
        return f"{now.year}-W{now.isocalendar()[1]}"
    if week.isdigit():
        return f"{now.year}-W{int(week)}"
    return week


def _on_login_required():
    """Notify the user that MitID authentication is needed."""
    click.echo("Session expired or not found. Please open your MitID app to approve the login.")


async def _get_client(ctx: click.Context) -> AulaApiClient:
    """Create an authenticated AulaApiClient."""
    username = get_mitid_username(ctx)
    token_storage = FileTokenStorage(DEFAULT_TOKEN_FILE)
    return await authenticate_and_create_client(
        username,
        token_storage,
        on_qr_codes=_print_qr_codes_in_terminal,
        on_login_required=_on_login_required,
    )


async def _get_widget_context(
    client: AulaApiClient, prof: "Profile",
) -> tuple[list[str], list[str], str] | None:
    """Extract child IDs, institution codes, and session UUID for widget API calls.

    Returns None and prints an error if data is unavailable.
    """
    child_filter = [
        str(child._raw["userId"])
        for child in prof.children
        if child._raw and "userId" in child._raw
    ]
    if not child_filter:
        click.echo("No child user IDs found in profile data.")
        return None

    institution_filter: list[str] = []
    for child in prof.children:
        if child._raw:
            inst_code = child._raw.get("institutionProfile", {}).get("institutionCode", "")
            if inst_code and str(inst_code) not in institution_filter:
                institution_filter.append(str(inst_code))

    try:
        profile_context = await client.get_profile_context()
        session_uuid = profile_context["data"]["userId"]
    except Exception as e:
        click.echo(f"Error fetching profile context: {e}")
        return None

    return child_filter, institution_filter, session_uuid


# Define commands
@cli.command()
@click.pass_context
@async_cmd
async def login(ctx):
    """Authenticate and initialize session"""
    async with await _get_client(ctx) as client:
        click.echo(f"Logged in. API URL: {client.api_url}")


@cli.command()
@click.pass_context
@async_cmd
async def profile(ctx):
    """Fetch profile list and display structured info."""
    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except ValueError as e:
            click.echo(f"Error fetching or parsing profile data: {e}")
            return
        except Exception as e:
            click.echo(f"An unexpected error occurred: {e}")
            return

        click.echo(f"Profile: {prof.display_name} (ID: {prof.profile_id})")

        if prof.institution_profile_ids:
            ids = ", ".join(str(i) for i in prof.institution_profile_ids)
            click.echo(f"  Institution Profile IDs: {ids}")

        if prof.children:
            click.echo(f"\nChildren ({len(prof.children)}):")
            for child in prof.children:
                click.echo(f"  {child.name}")
                click.echo(f"    ID:          {child.id}")
                click.echo(f"    Profile ID:  {child.profile_id}")
                if child.institution_name:
                    click.echo(f"    Institution: {child.institution_name}")
        else:
            click.echo("\nNo children associated with this profile.")


@cli.command()
@click.option("--child-id", type=int, help="Specify a single child ID.")
@click.pass_context
@async_cmd
async def overview(ctx, child_id):
    """Fetch the daily overview for a child or all children."""
    async with await _get_client(ctx) as client:
        child_ids = []
        child_names: dict[int, str] = {}

        if child_id:
            child_ids.append(child_id)
        else:
            try:
                prof: Profile = await client.get_profile()
                if not prof.children:
                    click.echo("No children found in profile.")
                    return
                for child in prof.children:
                    child_ids.append(child.id)
                    child_names[child.id] = child.name
            except Exception as e:
                click.echo(f"Error fetching profile: {e}")
                return

        for i, c_id in enumerate(child_ids):
            try:
                data: DailyOverview | None = await client.get_daily_overview(c_id)
                if data is None:
                    click.echo(f"{child_names.get(c_id, f'Child {c_id}')}: unavailable")
                    continue

                fallback = (
                    data.institution_profile.name if data.institution_profile else f"Child {c_id}"
                )
                name = child_names.get(c_id, fallback)
                status = data.status.name.replace("_", " ").title() if data.status else "Unknown"
                ip = data.institution_profile
                institution = ip.institution_name if ip else None
                group = data.main_group.name if data.main_group else None

                click.echo(f"{'=' * 50}")
                click.echo(f"  {name}  [{status}]")
                if institution or group:
                    click.echo(f"  {' / '.join(filter(None, [institution, group]))}")
                click.echo(f"{'=' * 50}")

                details = []
                if data.check_in_time:
                    details.append(("Check-in", data.check_in_time))
                if data.check_out_time:
                    details.append(("Check-out", data.check_out_time))
                if data.entry_time:
                    details.append(("Entry", data.entry_time))
                if data.exit_time:
                    details.append(("Exit", data.exit_time))
                if data.exit_with:
                    details.append(("Exit with", data.exit_with))
                if data.location:
                    details.append(("Location", data.location))
                if data.comment:
                    details.append(("Comment", data.comment))

                if details:
                    for label, value in details:
                        click.echo(f"  {label}: {value}")
                else:
                    click.echo("  No additional details.")

                if i < len(child_ids) - 1:
                    click.echo()

            except Exception as e:
                click.echo(f"Error fetching overview for child {c_id}: {e}")


@cli.command()
@click.option("--limit", type=int, default=5, help="Number of threads to fetch.")
@click.option("--unread", is_flag=True, default=False, help="Only show unread message threads.")
@click.option("--search", type=str, default=None, help="Search messages for the given text.")
@click.pass_context
@async_cmd
async def messages(ctx, limit, unread, search):
    """Fetch the latest message threads and their messages."""
    async with await _get_client(ctx) as client:
        if search:
            click.echo(f'Searching messages for "{search}"...\n')

            try:
                prof: Profile = await client.get_profile()
            except Exception as e:
                click.echo(f"Error fetching profile: {e}")
                return

            institution_codes: list[str] = []
            for child in prof.children:
                if child._raw:
                    code = child._raw.get("institutionProfile", {}).get(
                        "institutionCode", ""
                    )
                    if code and str(code) not in institution_codes:
                        institution_codes.append(str(code))

            try:
                results = await client.search_messages(
                    text=search,
                    institution_profile_ids=prof.institution_profile_ids,
                    institution_codes=institution_codes,
                    limit=limit,
                )
            except Exception as e:
                click.echo(f"Error searching messages: {e}")
                return

            if not results:
                click.echo("No messages found.")
                return

            for i, msg in enumerate(results):
                msg_raw = msg._raw or {}
                sender = msg_raw.get("sender", {}).get("fullName", "Unknown")
                send_date = msg_raw.get("sendDateTime", "")
                subject = msg_raw.get("threadSubject", "")

                click.echo(f"{'=' * 60}")
                if subject:
                    click.echo(f"  {subject}")
                click.echo(f"  {sender}  {send_date}")
                click.echo(f"  {'-' * 40}")
                content = msg.content.strip()
                if content:
                    for line in content.splitlines():
                        click.echo(f"  {line}")
                else:
                    click.echo("  (no message body)")

                if i < len(results) - 1:
                    click.echo()
            return

        filter_label = "unread" if unread else "latest"
        click.echo(f"Fetching the {filter_label} {limit} message threads...\n")

        try:
            filter_on = "unread" if unread else None
            threads: list[MessageThread] = await client.get_message_threads(
                filter_on=filter_on
            )
            threads = threads[:limit]
        except Exception as e:
            click.echo(f"Error fetching message threads: {e}")
            return

        if not threads:
            click.echo("No message threads found.")
            return

        for i, thread in enumerate(threads):
            raw = thread._raw or {}
            participants = [p.get("name", "?") for p in raw.get("participants", [])]
            last_updated = raw.get("lastUpdatedDate", "")

            # Thread header
            click.echo(f"{'=' * 60}")
            click.echo(f"  {thread.subject}")
            meta_parts = []
            if participants:
                meta_parts.append(", ".join(participants))
            if last_updated:
                meta_parts.append(last_updated)
            if meta_parts:
                click.echo(f"  {' | '.join(meta_parts)}")
            click.echo(f"{'=' * 60}")

            try:
                messages_list: list[Message] = await client.get_messages_for_thread(
                    thread.thread_id
                )
                if not messages_list:
                    click.echo("  (no messages)")
                else:
                    for msg in messages_list:
                        msg_raw = msg._raw or {}
                        sender = msg_raw.get("sender", {}).get("fullName", "Unknown")
                        send_date = msg_raw.get("sendDateTime", "")

                        click.echo(f"\n  {sender}  {send_date}")
                        click.echo(f"  {'-' * 40}")
                        for line in msg.content.splitlines():
                            click.echo(f"  {line}")
            except Exception as e:
                click.echo(f"  Error: {e}")

            if i < len(threads) - 1:
                click.echo()


@cli.command()
@click.option(
    "--institution-profile-id",
    multiple=True,
    type=int,
    help="Filter events by specific child ID(s).",
)
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=datetime.datetime.now(ZoneInfo("Europe/Copenhagen")),
    help="Start date for events (YYYY-MM-DD). Defaults to today.",
)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=(datetime.datetime.now(ZoneInfo("Europe/Copenhagen")) + datetime.timedelta(days=7)),
    help="End date for events (YYYY-MM-DD). Defaults to 7 days from today.",
)
@click.pass_context
@async_cmd
async def calendar(ctx, institution_profile_id, start_date, end_date):
    """Fetch calendar events for children."""
    async with await _get_client(ctx) as client:
        click.echo("Fetching calendar events...")

        institution_profile_ids = list(institution_profile_id)

        if not institution_profile_ids:
            try:
                prof = await client.get_profile()
                institution_profile_ids = prof.institution_profile_ids
            except Exception as e:
                click.echo(f"Error fetching profile to get child IDs: {e}")
                return

        ids_str = ", ".join(str(x) for x in institution_profile_ids)
        click.echo(f"Fetching for institution IDs: {ids_str}")

        try:
            events = await client.get_calendar_events(institution_profile_ids, start_date, end_date)

            if not events:
                click.echo("No calendar events found for the specified criteria.")
                return

            click.echo("\n--- Calendar Events Table ---")
            from .utils.table import build_calendar_table, print_calendar_table

            table_data = build_calendar_table(events)
            print_calendar_table(table_data)

        except Exception as e:
            click.echo(f"Error fetching calendar events: {e}")
            raise


@cli.command()
@click.option(
    "--institution-profile-id",
    multiple=True,
    type=int,
    help="Filter posts by specific institution profile ID(s).",
)
@click.option(
    "--limit",
    type=int,
    default=10,
    help="Maximum number of posts to fetch. Defaults to 10.",
)
@click.option(
    "--page",
    type=int,
    default=1,
    help="Page number to fetch. Defaults to 1.",
)
@click.pass_context
@async_cmd
async def posts(ctx, institution_profile_id, limit, page):
    """Fetch posts from Aula."""
    async with await _get_client(ctx) as client:
        institution_profile_ids = list(institution_profile_id)

        if not institution_profile_ids:
            try:
                prof = await client.get_profile()
                institution_profile_ids = prof.institution_profile_ids
            except Exception as e:
                click.echo(f"Error fetching profile: {e}")
                return

        try:
            posts_list = await client.get_posts(
                page=page,
                limit=limit,
                institution_profile_ids=institution_profile_ids,
            )

            if not posts_list:
                click.echo("No posts found.")
                return

            for i, post in enumerate(posts_list):
                date_str = post.timestamp.strftime("%Y-%m-%d %H:%M") if post.timestamp else ""

                click.echo(f"{'=' * 60}")
                click.echo(f"  {post.title}")
                meta = f"  {post.owner.full_name}"
                if date_str:
                    meta += f"  |  {date_str}"
                click.echo(meta)
                click.echo(f"{'=' * 60}")

                if post.content:
                    for line in post.content.splitlines():
                        click.echo(f"  {line}")

                if post.attachments:
                    click.echo(f"\n  Attachments: {len(post.attachments)}")

                if i < len(posts_list) - 1:
                    click.echo()

        except Exception as e:
            click.echo(f"Error fetching posts: {e}", err=True)
            raise


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
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        child_filter, institution_filter, session_uuid = widget_ctx

        from .const import WIDGET_MIN_UDDANNELSE

        try:
            opgaver = await client.get_mu_tasks(
                WIDGET_MIN_UDDANNELSE,
                child_filter,
                institution_filter,
                week,
                session_uuid,
            )
        except Exception as e:
            click.echo(f"Error fetching tasks: {e}")
            return

        click.echo(f"{'=' * 60}")
        click.echo(f"  Min Uddannelse Tasks  [{week}]")
        click.echo(f"{'=' * 60}")

        if not opgaver:
            click.echo("  No tasks found.")
        else:
            for task in opgaver:
                click.echo(f"\n  {task.title}")
                click.echo(f"  {'-' * 40}")
                if task.student_name:
                    click.echo(f"  Student: {task.student_name}")
                if task.weekday:
                    click.echo(f"  Day:     {task.weekday}")
                if task.task_type:
                    click.echo(f"  Type:    {task.task_type}")
                for cls in task.classes:
                    click.echo(f"  Class:   {cls.name} ({cls.subject_name})")
                if task.course:
                    click.echo(f"  Course:  {task.course.name}")


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
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        child_filter, institution_filter, session_uuid = widget_ctx

        from .const import WIDGET_MIN_UDDANNELSE_UGEPLAN
        from .utils.html import html_to_plain

        try:
            personer = await client.get_ugeplan(
                WIDGET_MIN_UDDANNELSE_UGEPLAN,
                child_filter,
                institution_filter,
                week,
                session_uuid,
            )
        except Exception as e:
            click.echo(f"Error fetching weekly plans: {e}")
            return

        if not personer:
            click.echo("No weekly plans found.")
            return

        for person in personer:
            for inst in person.institutions:
                for letter in inst.letters:
                    click.echo(f"{'=' * 60}")
                    click.echo(f"  {person.name}  [{letter.group_name}]")
                    click.echo(f"  {inst.name}  |  Week {letter.week_number}")
                    click.echo(f"{'=' * 60}")
                    click.echo()
                    for line in html_to_plain(letter.content_html).splitlines():
                        click.echo(f"  {line}")
                    click.echo()


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
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        institution_filter: list[str] = []
        for child in prof.children:
            if child._raw:
                inst_code = child._raw.get("institutionProfile", {}).get("institutionCode", "")
                if inst_code and str(inst_code) not in institution_filter:
                    institution_filter.append(str(inst_code))

        try:
            profile_context = await client.get_profile_context()
            session_uuid = profile_context["data"]["userId"]
        except Exception as e:
            click.echo(f"Error fetching profile context: {e}")
            return

        for child in prof.children:
            if not child._raw or "userId" not in child._raw:
                continue
            child_id = str(child._raw["userId"])

            try:
                appointments = await client.get_easyiq_weekplan(
                    week, session_uuid, institution_filter, child_id
                )
            except Exception as e:
                click.echo(f"Error fetching EasyIQ weekplan for {child.name}: {e}")
                continue

            click.echo(f"{'=' * 60}")
            click.echo(f"  {child.name}  |  EasyIQ Ugeplan  [{week}]")
            click.echo(f"{'=' * 60}")

            if not appointments:
                click.echo("  No appointments found.")
            else:
                for appt in appointments:
                    click.echo(f"\n  {appt.title}")
                    if appt._raw:
                        start = appt._raw.get("start", "")
                        end = appt._raw.get("end", "")
                        if start or end:
                            click.echo(f"  {start} - {end}")
                        description = appt._raw.get("description", "")
                        if description:
                            from .utils.html import html_to_plain

                            for line in html_to_plain(description).splitlines():
                                click.echo(f"    {line}")

            click.echo()


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
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        child_filter = [
            str(child._raw["userId"])
            for child in prof.children
            if child._raw and "userId" in child._raw
        ]
        if not child_filter:
            click.echo("No child user IDs found in profile data.")
            return

        institution_filter: list[str] = []
        for child in prof.children:
            if child._raw:
                inst_code = child._raw.get("institutionProfile", {}).get("institutionCode", "")
                if inst_code and str(inst_code) not in institution_filter:
                    institution_filter.append(str(inst_code))

        try:
            profile_context = await client.get_profile_context()
            session_uuid = profile_context["data"]["userId"]
        except Exception as e:
            click.echo(f"Error fetching profile context: {e}")
            return

        try:
            students = await client.get_meebook_weekplan(
                child_filter, institution_filter, week, session_uuid
            )
        except Exception as e:
            click.echo(f"Error fetching Meebook weekplan: {e}")
            return

        if not students:
            click.echo("No weekly plans found.")
            return

        from .utils.html import html_to_plain

        for student in students:
            click.echo(f"{'=' * 60}")
            click.echo(f"  {student.name}  |  Meebook Ugeplan  [{week}]")
            click.echo(f"{'=' * 60}")

            if not student.week_plan:
                click.echo("  No plan for this week.")
                continue

            for day in student.week_plan:
                if not day.tasks:
                    continue
                click.echo(f"\n  {day.date}")
                click.echo(f"  {'-' * 40}")
                for task in day.tasks:
                    label = task.title or task.type
                    if task.pill:
                        label = f"[{task.pill}] {label}"
                    click.echo(f"  {label}")
                    if task.content:
                        for line in html_to_plain(task.content).splitlines():
                            click.echo(f"    {line}")

            click.echo()


@cli.command("momo:forløb")
@click.pass_context
@async_cmd
async def momo_course(ctx):
    """Fetch MoMo courses (forløb) for children."""
    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        children = [
            str(child._raw["userId"])
            for child in prof.children
            if child._raw and "userId" in child._raw
        ]
        if not children:
            click.echo("No child user IDs found in profile data.")
            return

        institutions: list[str] = []
        for child in prof.children:
            if child._raw:
                inst_code = child._raw.get("institutionProfile", {}).get("institutionCode", "")
                if inst_code and str(inst_code) not in institutions:
                    institutions.append(str(inst_code))

        try:
            profile_context = await client.get_profile_context()
            session_uuid = profile_context["data"]["userId"]
        except Exception as e:
            click.echo(f"Error fetching profile context: {e}")
            return

        try:
            users_with_courses = await client.get_momo_courses(children, institutions, session_uuid)
        except Exception as e:
            click.echo(f"Error fetching MoMo courses: {e}")
            return

        if not users_with_courses:
            click.echo("No courses found.")
            return

        for user in users_with_courses:
            name = user.name.split()[0] if user.name else "Unknown"

            click.echo(f"{'=' * 60}")
            click.echo(f"  {name}  |  MoMo Course")
            click.echo(f"{'=' * 60}")

            if not user.courses:
                click.echo("  No courses.")
            else:
                for course in user.courses:
                    click.echo(f"\n  {course.title}")
                    click.echo(f"  {'-' * 40}")

            click.echo()


@cli.command("download-images")
@click.option(
    "--output",
    type=click.Path(),
    default="./aula_images",
    help="Output directory for downloaded images.",
)
@click.option(
    "--since",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Only download images from this date onwards (YYYY-MM-DD).",
)
@click.option(
    "--source",
    type=click.Choice(["all", "gallery", "posts", "messages"], case_sensitive=False),
    default="all",
    help="Which source(s) to download from.",
)
@click.option(
    "--tags",
    multiple=True,
    help="Filter gallery images by tag (can be specified multiple times).",
)
@click.pass_context
@async_cmd
async def download_images(ctx, output, since, source, tags):
    """Download images from Aula (gallery, posts, messages)."""
    from pathlib import Path

    from .utils.download import (
        download_gallery_images,
        download_message_images,
        download_post_images,
    )

    output_path = Path(output)
    cutoff = since.date()
    tag_list = list(tags) if tags else None

    async with await _get_client(ctx) as client:
        prof = await client.get_profile()
        institution_profile_ids = prof.institution_profile_ids

        # Children's institution profile IDs and institution codes (for message search)
        children_inst_ids = [child.id for child in prof.children]
        institution_codes: list[str] = []
        for child in prof.children:
            if child._raw:
                code = child._raw.get("institutionProfile", {}).get("institutionCode", "")
                if code and code not in institution_codes:
                    institution_codes.append(code)

        total_downloaded = 0
        total_skipped = 0

        if source in ("all", "gallery"):
            click.echo("Gallery")
            dl, sk = await download_gallery_images(
                client, institution_profile_ids, output_path, cutoff, tag_list,
                on_progress=click.echo,
            )
            click.echo(f"  Done: {dl} downloaded, {sk} skipped\n")
            total_downloaded += dl
            total_skipped += sk

        if source in ("all", "posts"):
            click.echo("Posts")
            dl, sk = await download_post_images(
                client, institution_profile_ids, output_path, cutoff,
                on_progress=click.echo,
            )
            click.echo(f"  Done: {dl} downloaded, {sk} skipped\n")
            total_downloaded += dl
            total_skipped += sk

        if source in ("all", "messages"):
            click.echo("Messages")
            dl, sk = await download_message_images(
                client, children_inst_ids, institution_codes, output_path, cutoff,
                on_progress=click.echo,
            )
            click.echo(f"  Done: {dl} downloaded, {sk} skipped\n")
            total_downloaded += dl
            total_skipped += sk

        click.echo(f"\nTotal: {total_downloaded} downloaded, {total_skipped} skipped")


@cli.command("library:status")
@click.pass_context
@async_cmd
async def library_status(ctx):
    """Fetch library loans and reservations for children."""
    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        children, institutions, session_uuid = widget_ctx

        from .const import WIDGET_BIBLIOTEKET

        try:
            status = await client.get_library_status(
                WIDGET_BIBLIOTEKET,
                children,
                institutions,
                session_uuid,
            )
        except Exception as e:
            click.echo(f"Error fetching library status: {e}")
            return

        click.echo(f"{'=' * 60}")
        click.echo("  Library Status")
        click.echo(f"{'=' * 60}")

        if status.loans:
            click.echo(f"\n  Loans ({len(status.loans)})")
            for loan in status.loans:
                click.echo(f"\n  {loan.title}")
                click.echo(f"  {'-' * 40}")
                if loan.author:
                    click.echo(f"  Author:   {loan.author}")
                click.echo(f"  Borrower: {loan.patron_display_name}")
                click.echo(f"  Due date: {loan.due_date}")
        else:
            click.echo("\n  No active loans.")

        if status.longterm_loans:
            click.echo(f"\n  Long-term loans ({len(status.longterm_loans)})")
            for loan in status.longterm_loans:
                click.echo(f"\n  {loan.title}")
                click.echo(f"  {'-' * 40}")
                if loan.author:
                    click.echo(f"  Author:   {loan.author}")
                click.echo(f"  Borrower: {loan.patron_display_name}")
                click.echo(f"  Due date: {loan.due_date}")

        if status.reservations:
            click.echo(f"\n  Reservations ({len(status.reservations)})")
            for res in status.reservations:
                click.echo(f"  - {res}")

        if not status.loans and not status.longterm_loans and not status.reservations:
            click.echo("\n  No loans or reservations found.")

        click.echo()


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
    from .utils.html import html_to_plain

    week = _resolve_week(week)

    # ── Provider resolution ──────────────────────────────────────────────────
    _log = logging.getLogger(__name__)
    if providers:
        enabled: set[WeeklySummaryProvider] = (
            set(WeeklySummaryProvider)
            if "all" in providers
            else {WeeklySummaryProvider(p) for p in providers}
        )
    else:
        cfg = load_config().get("weekly_summary", {})
        enabled = set()
        for key, active in cfg.items():
            try:
                provider = WeeklySummaryProvider(key)
            except ValueError:
                _log.warning("Unknown weekly_summary provider in config: %r (ignored)", key)
                continue
            if active:
                enabled.add(provider)

    year_num, week_num = week.split("-W")
    week_start = datetime.datetime.fromisocalendar(
        int(year_num), int(week_num), 1
    ).replace(tzinfo=ZoneInfo("Europe/Copenhagen"))
    week_end = datetime.datetime.fromisocalendar(
        int(year_num), int(week_num), 5
    ).replace(tzinfo=ZoneInfo("Europe/Copenhagen"), hour=23, minute=59, second=59)

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        # Filter children by name if --child provided
        children = prof.children
        if child:
            needle = child.lower()
            children = [c for c in prof.children if needle in c.name.lower()]
            if not children:
                names = ", ".join(c.name for c in prof.children)
                click.echo(f"No child matching '{child}'. Available: {names}")
                return

        now = datetime.datetime.now(ZoneInfo("Europe/Copenhagen"))
        click.echo(f"# Weekly Overview – Week {week_num}, {year_num}")
        click.echo(f"Generated: {now.strftime('%Y-%m-%d')}")
        click.echo(
            f"Period: {week_start.strftime('%a %d %b')} – {week_end.strftime('%a %d %b %Y')}"
        )
        click.echo()

        # ── Calendar events ──────────────────────────────────────────────────
        child_inst_ids = [c.id for c in children]
        try:
            events = await client.get_calendar_events(child_inst_ids, week_start, week_end)
        except Exception as e:
            events = []
            logging.getLogger(__name__).warning("Could not fetch calendar events: %s", e)

        click.echo("## Calendar Events")
        click.echo()
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
                click.echo(f"### {day_label}")
                if day_events:
                    # Merge events that share the exact same timeslot
                    slots: dict[tuple, list] = defaultdict(list)
                    for ev in day_events:
                        slots[(ev.start_datetime, ev.end_datetime)].append(ev)
                    for (start_dt, end_dt), evs in sorted(slots.items()):
                        time_range = (
                            f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
                        )
                        titles = " / ".join(dict.fromkeys(ev.title or "Untitled" for ev in evs))
                        locations = list(dict.fromkeys(ev.location for ev in evs if ev.location))
                        teachers = list(
                            dict.fromkeys(ev.teacher_name for ev in evs if ev.teacher_name)
                        )
                        substitutes = list(
                            dict.fromkeys(
                                ev.substitute_name
                                for ev in evs
                                if ev.has_substitute and ev.substitute_name
                            )
                        )
                        parts = [time_range, titles]
                        if locations:
                            parts.append(f"({' / '.join(locations)})")
                        if teachers:
                            parts.append(f"[{' / '.join(teachers)}]")
                        if substitutes:
                            parts.append(f"[Substitute: {' / '.join(substitutes)}]")
                        click.echo(f"- {'  '.join(parts)}")
                else:
                    click.echo("- (no events)")
                click.echo()
        else:
            click.echo("No calendar events found.")
            click.echo()

        if not enabled:
            return  # nothing to fetch beyond calendar

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            click.echo("(Widget context unavailable – skipping provider data)")
            return

        child_filter, institution_filter, session_uuid = widget_ctx

        # Filter child_filter to selected children only
        if child:
            selected_user_ids = {
                str(c._raw["userId"])
                for c in children
                if c._raw and "userId" in c._raw
            }
            child_filter = [uid for uid in child_filter if uid in selected_user_ids]

        # ── Min Uddannelse – Homework & Tasks ────────────────────────────────
        if WeeklySummaryProvider.MU_OPGAVER in enabled:
            from .const import WIDGET_MIN_UDDANNELSE

            try:
                tasks = await client.get_mu_tasks(
                    WIDGET_MIN_UDDANNELSE,
                    child_filter,
                    institution_filter,
                    week,
                    session_uuid,
                )
            except Exception as e:
                tasks = []
                _log.warning("Could not fetch MU tasks: %s", e)

            click.echo("## Homework & Tasks (Min Uddannelse)")
            click.echo()
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
                    click.echo(f"- {label}{status}")
                    if task.task_type:
                        click.echo(f"  Type: {task.task_type}")
            else:
                click.echo("No tasks found.")
            click.echo()

        # ── Min Uddannelse – Weekly Letter (Ugeplan) ─────────────────────────
        if WeeklySummaryProvider.MU_UGEPLAN in enabled:
            from .const import WIDGET_MIN_UDDANNELSE_UGEPLAN

            try:
                mu_persons = await client.get_ugeplan(
                    WIDGET_MIN_UDDANNELSE_UGEPLAN,
                    child_filter,
                    institution_filter,
                    week,
                    session_uuid,
                )
            except Exception as e:
                mu_persons = []
                _log.warning("Could not fetch MU ugeplan: %s", e)

            if mu_persons:
                click.echo("## Weekly Letter (Min Uddannelse Ugeplan)")
                click.echo()
                for person in mu_persons:
                    for inst in person.institutions:
                        for letter in inst.letters:
                            click.echo(f"### {person.name} – {letter.group_name} ({inst.name})")
                            click.echo()
                            for line in html_to_plain(letter.content_html).splitlines():
                                click.echo(line)
                            click.echo()

        # ── Meebook – Weekly Plan ────────────────────────────────────────────
        if WeeklySummaryProvider.MEEBOOK in enabled:
            try:
                meebook_students = await client.get_meebook_weekplan(
                    child_filter, institution_filter, week, session_uuid
                )
            except Exception as e:
                meebook_students = []
                _log.warning("Could not fetch Meebook weekplan: %s", e)

            if meebook_students:
                click.echo("## Weekly Plan (Meebook)")
                click.echo()
                for student in meebook_students:
                    click.echo(f"### {student.name}")
                    click.echo()
                    for day in student.week_plan:
                        if not day.tasks:
                            continue
                        click.echo(f"**{day.date}**")
                        for task in day.tasks:
                            label = task.title or task.type
                            if task.pill:
                                label = f"[{task.pill}] {label}"
                            click.echo(f"- {label}")
                            if task.content:
                                for line in html_to_plain(task.content).splitlines():
                                    if line.strip():
                                        click.echo(f"  {line}")
                    click.echo()

        # ── EasyIQ – Weekly Plan ─────────────────────────────────────────────
        if WeeklySummaryProvider.EASYIQ in enabled:
            easyiq_any = False
            for c in children:
                if not c._raw or "userId" not in c._raw:
                    continue
                c_user_id = str(c._raw["userId"])
                c_institutions: list[str] = []
                inst_code = c._raw.get("institutionProfile", {}).get("institutionCode", "")
                if inst_code:
                    c_institutions.append(str(inst_code))

                try:
                    appointments = await client.get_easyiq_weekplan(
                        week, session_uuid, c_institutions or institution_filter, c_user_id
                    )
                except Exception as e:
                    _log.warning("Could not fetch EasyIQ weekplan for %s: %s", c.name, e)
                    continue

                if not appointments:
                    continue

                if not easyiq_any:
                    click.echo("## Weekly Plan (EasyIQ)")
                    click.echo()
                    easyiq_any = True

                click.echo(f"### {c.name}")
                click.echo()
                for appt in appointments:
                    click.echo(f"- {appt.title}")
                    if appt._raw:
                        start = appt._raw.get("start", "")
                        end = appt._raw.get("end", "")
                        if start or end:
                            click.echo(f"  {start} – {end}")
                        description = appt._raw.get("description", "")
                        if description:
                            for line in html_to_plain(description).splitlines():
                                if line.strip():
                                    click.echo(f"  {line}")
                click.echo()


if __name__ == "__main__":
    cli()
