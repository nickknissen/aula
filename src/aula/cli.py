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

# On Windows, use SelectorEventLoopPolicy to avoid 'Event loop closed' issues
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from .api_client import AulaApiClient
from .auth_flow import authenticate_and_create_client
from .config import CONFIG_FILE, DEFAULT_TOKEN_FILE, load_config, save_config
from .models import DailyOverview, Message, MessageThread, Notification, Profile
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
    EASYIQ_HOMEWORK = "easyiq_homework"


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
    log_level = logging.ERROR  # Default: errors only (no warnings in normal output)
    if verbose == 1:
        log_level = logging.WARNING  # -v: Show warnings and above
    elif verbose == 2:
        log_level = logging.INFO  # -vv: Show info and above
    elif verbose >= 3:
        log_level = logging.DEBUG  # -vvv: Show debug and above

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
    client: AulaApiClient,
    prof: "Profile",
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
                status = data.status.display_name if data.status else "Unknown"
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
                    code = child._raw.get("institutionProfile", {}).get("institutionCode", "")
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
            threads: list[MessageThread] = await client.get_message_threads(filter_on=filter_on)
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
@click.option("--offset", type=int, default=0, show_default=True, help="Pagination offset.")
@click.option("--limit", type=int, default=20, show_default=True, help="Maximum items to fetch.")
@click.option("--module", type=str, default=None, help="Optional module filter.")
@click.pass_context
@async_cmd
async def notifications(ctx, offset, limit, module):
    """Fetch notifications for the active profile."""
    async with await _get_client(ctx) as client:
        try:
            items: list[Notification] = await client.get_notifications_for_active_profile(
                offset=offset,
                limit=limit,
                module=module,
            )
        except Exception as e:
            click.echo(f"Error fetching notifications: {e}")
            return

        if not items:
            click.echo("No notifications found.")
            return

        for i, item in enumerate(items):
            created = item.created_at or ""
            module_name = item.module or "unknown"
            read_flag = "unknown"
            if item.is_read is True:
                read_flag = "read"
            elif item.is_read is False:
                read_flag = "unread"
            click.echo(f"[{item.id}] {item.title}")

            line1 = f"module={module_name}"
            if item.event_type:
                line1 = f"{line1} event={item.event_type}"
            if item.notification_type:
                line1 = f"{line1} type={item.notification_type}"
            line1 = f"{line1} status={read_flag}"
            click.echo(f"  {line1}")

            line2 = ""
            if created:
                line2 = f"triggered={created}"
            if item.expires_at:
                line2 = f"{line2} expires={item.expires_at}".strip()
            if line2:
                click.echo(f"  {line2}")

            line3 = ""
            if item.institution_code:
                line3 = f"institution={item.institution_code}"
            if item.related_child_name:
                line3 = f"{line3} child={item.related_child_name}".strip()
            if line3:
                click.echo(f"  {line3}")

            refs: list[str] = []
            if item.post_id is not None:
                refs.append(f"post={item.post_id}")
            if item.album_id is not None:
                refs.append(f"album={item.album_id}")
            if item.media_id is not None:
                refs.append(f"media={item.media_id}")
            if refs:
                click.echo(f"  {' '.join(refs)}")

            if i < len(items) - 1:
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
            opgaver = await client.widgets.get_mu_tasks(
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
            personer = await client.widgets.get_ugeplan(
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
                appointments = await client.widgets.get_easyiq_weekplan(
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
                    if appt.start or appt.end:
                        click.echo(f"  {appt.start} - {appt.end}")
                    if appt.description:
                        from .utils.html import html_to_plain

                        for line in html_to_plain(appt.description).splitlines():
                            click.echo(f"    {line}")

            click.echo()


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

        from .utils.html import html_to_plain

        for child in prof.children:
            if not child._raw or "userId" not in child._raw:
                continue
            child_id = str(child._raw["userId"])

            try:
                homework = await client.widgets.get_easyiq_homework(
                    week, session_uuid, institution_filter, child_id
                )
            except Exception as e:
                click.echo(f"Error fetching EasyIQ homework for {child.name}: {e}")
                continue

            click.echo(f"{'=' * 60}")
            click.echo(f"  {child.name}  |  EasyIQ Homework  [{week}]")
            click.echo(f"{'=' * 60}")

            if not homework:
                click.echo("  No homework found.")
            else:
                for hw in homework:
                    status = "[x]" if hw.is_completed else "[ ]"
                    click.echo(f"\n  {status} {hw.title}")
                    if hw.subject:
                        click.echo(f"      Subject: {hw.subject}")
                    if hw.due_date:
                        click.echo(f"      Due: {hw.due_date}")
                    if hw.description:
                        for line in html_to_plain(hw.description).splitlines():
                            click.echo(f"      {line}")

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
            students = await client.widgets.get_meebook_weekplan(
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
            users_with_courses = await client.widgets.get_momo_courses(
                children, institutions, session_uuid
            )
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


@cli.command("momo:huskeliste")
@click.pass_context
@async_cmd
async def momo_reminders(ctx):
    """Fetch MoMo reminders (huskelisten) for children."""
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

        today = datetime.date.today()
        from_date = today.isoformat()
        due_no_later_than = (today + datetime.timedelta(days=7)).isoformat()

        try:
            users = await client.widgets.get_momo_reminders(
                children, institutions, session_uuid, from_date, due_no_later_than
            )
        except Exception as e:
            click.echo(f"Error fetching reminders: {e}")
            return

        if not users:
            click.echo("No reminders found.")
            return

        tz = ZoneInfo("Europe/Copenhagen")
        for user in users:
            name = user.user_name.split()[0] if user.user_name else "Unknown"

            click.echo(f"{'=' * 60}")
            click.echo(f"  {name}  |  Huskelisten")
            click.echo(f"{'=' * 60}")

            all_reminders = user.team_reminders + user.assignment_reminders
            if not all_reminders:
                click.echo("  Ingen påmindelser.")
                click.echo()
                continue

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
                click.echo(f"\n  {due}")
                click.echo(f"  {r.subject_name} — af {r.created_by}")
                click.echo(f"  {r.team_name}")
                click.echo(f"  {r.reminder_text}")

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
                click.echo(f"\n  {due}")
                if teams:
                    click.echo(f"  {teams}")
                click.echo(f"  {r.assignment_text}")

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
                client,
                institution_profile_ids,
                output_path,
                cutoff,
                tag_list,
                on_progress=click.echo,
            )
            click.echo(f"  Done: {dl} downloaded, {sk} skipped\n")
            total_downloaded += dl
            total_skipped += sk

        if source in ("all", "posts"):
            click.echo("Posts")
            dl, sk = await download_post_images(
                client,
                institution_profile_ids,
                output_path,
                cutoff,
                on_progress=click.echo,
            )
            click.echo(f"  Done: {dl} downloaded, {sk} skipped\n")
            total_downloaded += dl
            total_skipped += sk

        if source in ("all", "messages"):
            click.echo("Messages")
            dl, sk = await download_message_images(
                client,
                children_inst_ids,
                institution_codes,
                output_path,
                cutoff,
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
            status = await client.widgets.get_library_status(
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
                day_label = (week_start + datetime.timedelta(days=day_offset)).strftime("%A, %d %B")
                day_events = sorted(by_day.get(day, []), key=lambda e: e.start_datetime)
                click.echo(f"### {day_label}")
                if day_events:
                    # Merge events that share the exact same timeslot
                    slots: dict[tuple, list] = defaultdict(list)
                    for ev in day_events:
                        slots[(ev.start_datetime, ev.end_datetime)].append(ev)
                    for (start_dt, end_dt), evs in sorted(slots.items()):
                        time_range = f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
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

        # ── Unread messages ──────────────────────────────────────────────────
        try:
            unread_threads = await client.get_message_threads(filter_on="unread")
        except Exception as e:
            unread_threads = []
            _log.warning("Could not fetch unread messages: %s", e)

        if unread_threads:
            click.echo("## Unread Messages")
            click.echo()
            for thread in unread_threads:
                raw = thread._raw or {}
                participants = [p.get("name", "?") for p in raw.get("participants", [])]
                last_updated = raw.get("lastUpdatedDate", "")
                meta = []
                if participants:
                    meta.append(", ".join(participants))
                if last_updated:
                    meta.append(last_updated)
                click.echo(f"### {thread.subject}")
                if meta:
                    click.echo(f"_{' | '.join(meta)}_")
                click.echo()
                try:
                    msgs = await client.get_messages_for_thread(thread.thread_id)
                    for msg in msgs:
                        msg_raw = msg._raw or {}
                        sender = msg_raw.get("sender", {}).get("fullName", "Unknown")
                        send_date = msg_raw.get("sendDateTime", "")
                        click.echo(f"**{sender}** {send_date}".strip())
                        for line in msg.content.splitlines():
                            if line.strip():
                                click.echo(line)
                        click.echo()
                except Exception as e:
                    _log.warning("Could not fetch messages for thread %s: %s", thread.thread_id, e)
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
                str(c._raw["userId"]) for c in children if c._raw and "userId" in c._raw
            }
            child_filter = [uid for uid in child_filter if uid in selected_user_ids]

        # ── Min Uddannelse – Homework & Tasks ────────────────────────────────
        if WeeklySummaryProvider.MU_OPGAVER in enabled:
            from .const import WIDGET_MIN_UDDANNELSE

            try:
                tasks = await client.widgets.get_mu_tasks(
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
                mu_persons = await client.widgets.get_ugeplan(
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
                meebook_students = await client.widgets.get_meebook_weekplan(
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
                    appointments = await client.widgets.get_easyiq_weekplan(
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
                    if appt.start or appt.end:
                        click.echo(f"  {appt.start} – {appt.end}")
                    if appt.description:
                        for line in html_to_plain(appt.description).splitlines():
                            if line.strip():
                                click.echo(f"  {line}")
                click.echo()

        # ── EasyIQ – Homework ──────────────────────────────────────────────────
        if WeeklySummaryProvider.EASYIQ_HOMEWORK in enabled:
            easyiq_hw_any = False
            for c in children:
                if not c._raw or "userId" not in c._raw:
                    continue
                c_user_id = str(c._raw["userId"])
                c_institutions: list[str] = []
                inst_code = c._raw.get("institutionProfile", {}).get("institutionCode", "")
                if inst_code:
                    c_institutions.append(str(inst_code))

                try:
                    homework = await client.widgets.get_easyiq_homework(
                        week, session_uuid, c_institutions or institution_filter, c_user_id
                    )
                except Exception as e:
                    _log.warning("Could not fetch EasyIQ homework for %s: %s", c.name, e)
                    continue

                if not homework:
                    continue

                if not easyiq_hw_any:
                    click.echo("## Homework (EasyIQ)")
                    click.echo()
                    easyiq_hw_any = True

                click.echo(f"### {c.name}")
                click.echo()
                for hw in homework:
                    status = "[x]" if hw.is_completed else "[ ]"
                    click.echo(f"- {status} {hw.title}")
                    if hw.subject:
                        click.echo(f"  Subject: {hw.subject}")
                    if hw.due_date:
                        click.echo(f"  Due: {hw.due_date}")
                    if hw.description:
                        for line in html_to_plain(hw.description).splitlines():
                            if line.strip():
                                click.echo(f"  {line}")
                click.echo()


@cli.command("presence-templates")
@click.option(
    "--from-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Start date (YYYY-MM-DD). Defaults to today.",
)
@click.option(
    "--to-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="End date (YYYY-MM-DD). Defaults to 7 days from today.",
)
@click.pass_context
@async_cmd
async def presence_templates(ctx, from_date, to_date):
    """Fetch presence week templates (planned entry/exit times) for all children."""
    tz = ZoneInfo("Europe/Copenhagen")
    now = datetime.datetime.now(tz)

    from_date_d = from_date.date() if from_date else now.date()
    to_date_d = to_date.date() if to_date else (now + datetime.timedelta(days=7)).date()

    if from_date_d > to_date_d:
        click.echo(
            f"Error: --from-date ({from_date_d}) must be on or before --to-date ({to_date_d})",
            err=True,
        )
        return

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        institution_profile_ids = [child.id for child in prof.children]

        try:
            templates = await client.get_presence_templates(
                institution_profile_ids, from_date_d, to_date_d
            )
        except Exception as e:
            click.echo(f"Error fetching presence templates: {e}")
            return

        if not templates:
            click.echo("No presence templates found.")
            return

        for tmpl in templates:
            ip = tmpl.institution_profile
            if not ip:
                _log = logging.getLogger(__name__)
                _log.warning("Presence template has no institution profile")
                name = "Unknown"
                institution = ""
            else:
                name = ip.name
                institution = ip.institution_name

            click.echo(f"{'=' * 60}")
            header = name or "Unknown"
            if institution:
                header = f"{header}  |  {institution}"
            click.echo(f"  {header}")
            click.echo(f"{'=' * 60}")

            if not tmpl.day_templates:
                click.echo("  No day templates.")
            else:
                for day in tmpl.day_templates:
                    click.echo(f"\n  {day.by_date}")
                    if day.entry_time or day.exit_time:
                        times = f"  {day.entry_time or '?'} → {day.exit_time or '?'}"
                        if day.exit_with:
                            times = f"{times}  (picked up by: {day.exit_with})"
                        click.echo(times)
                    if day.spare_time_activity:
                        sta = day.spare_time_activity
                        click.echo(f"  Activity: {sta.start_time} – {sta.end_time}")
                        if sta.comment:
                            click.echo(f"    {sta.comment}")
                    if day.comment:
                        click.echo(f"  Note: {day.comment}")

            click.echo()


_DANISH_WEEKDAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]


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

    _log = logging.getLogger(__name__)
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
    today_weekday_da = _DANISH_WEEKDAYS[today.weekday()]
    day_label = today.strftime("%A, %d %B %Y")

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        children = prof.children
        if child:
            needle = child.lower()
            children = [c for c in prof.children if needle in c.name.lower()]
            if not children:
                names = ", ".join(c.name for c in prof.children)
                click.echo(f"No child matching '{child}'. Available: {names}")
                return

        click.echo(f"# Daily Summary – {day_label}")
        click.echo(f"Generated: {now.strftime('%Y-%m-%d %H:%M')}")
        click.echo()

        # ── Presence templates for target date (planned times) ────────────────
        # Extract institution profile IDs from children (Child.id, not profile_id)
        child_institution_profile_ids = [c.id for c in children]
        try:
            presence_tmpl_list = await client.get_presence_templates(
                child_institution_profile_ids, today.date(), today.date()
            )
        except Exception as e:
            presence_tmpl_list = []
            _log.warning("Could not fetch presence templates: %s", e)

        from .models import DayTemplate

        # Log ID mapping for verification (debug only)
        _log.debug("=== ID MAPPING VERIFICATION ===")
        _log.debug("Children and their IDs:")
        for c in children:
            _log.debug("  Child: %s | id=%s | profile_id=%s", c.name, c.id, c.profile_id)
        _log.debug("Presence templates and their institution profile IDs:")
        for tmpl in presence_tmpl_list:
            if tmpl.institution_profile:
                _log.debug(
                    "  Template: %s | id=%s | profile_id=%s",
                    tmpl.institution_profile.name or "unknown",
                    tmpl.institution_profile.id,
                    tmpl.institution_profile.profile_id,
                )
        _log.debug("=== END ID MAPPING VERIFICATION ===")

        # Find day template matching target date
        target_date_str = today.date().isoformat()
        day_template_by_child: dict[int, DayTemplate] = {}
        for tmpl in presence_tmpl_list:
            if not tmpl.institution_profile:
                _log.warning("Presence template has no institution profile, skipping")
                continue
            if not tmpl.day_templates:
                _log.warning(
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
        click.echo("## Status")
        click.echo()
        for c in children:
            day_tmpl = day_template_by_child.get(c.id)

            ov = None
            if is_today:
                try:
                    ov = await client.get_daily_overview(c.id)
                except Exception as e:
                    _log.warning("Could not fetch daily overview for %s: %s", c.name, e)

            click.echo(f"**{c.name}**")

            if ov is not None:
                status = ov.status.display_name if ov.status else "Unknown"
                click.echo(f"- Status: {status}")
                if ov.check_in_time:
                    click.echo(f"- Check-in: {ov.check_in_time}")
                if ov.check_out_time:
                    click.echo(f"- Check-out: {ov.check_out_time}")
                if ov.location:
                    click.echo(f"- Location: {ov.location}")
                if ov.main_group:
                    click.echo(f"- Group: {ov.main_group.name}")

            # Show actual times from daily overview, with planned times as fallback
            if ov is not None and ov.entry_time:
                click.echo(f"- Entry: {ov.entry_time}")
            elif day_tmpl and day_tmpl.entry_time:
                click.echo(f"- Planned entry: {day_tmpl.entry_time}")

            if ov is not None and ov.exit_time:
                click.echo(f"- Exit: {ov.exit_time}")
            elif day_tmpl and day_tmpl.exit_time:
                click.echo(f"- Planned exit: {day_tmpl.exit_time}")

            if ov is not None and ov.exit_with:
                click.echo(f"- Picked up by: {ov.exit_with}")
            elif day_tmpl and day_tmpl.exit_with:
                click.echo(f"- Picked up by (planned): {day_tmpl.exit_with}")

            if ov is not None and ov.comment:
                click.echo(f"- Note: {ov.comment}")

            if day_tmpl and day_tmpl.spare_time_activity:
                sta = day_tmpl.spare_time_activity
                if sta.start_time and sta.end_time:
                    activity_line = f"- Activity: {sta.start_time}–{sta.end_time}"
                    if sta.comment:
                        activity_line = f"{activity_line}  ({sta.comment})"
                    click.echo(activity_line)

            if ov is None and not day_tmpl:
                click.echo("- No data available")

            click.echo()

        # ── Schedule ──────────────────────────────────────────────────────────
        try:
            events = await client.get_calendar_events(
                child_institution_profile_ids, day_start, day_end
            )
        except Exception as e:
            events = []
            _log.warning("Could not fetch calendar events: %s", e)

        click.echo("## Schedule")
        click.echo()
        if events:
            slots: dict[tuple, list] = defaultdict(list)
            for ev in sorted(events, key=lambda e: e.start_datetime):
                slots[(ev.start_datetime, ev.end_datetime)].append(ev)
            for (start_dt, end_dt), evs in sorted(slots.items()):
                time_range = f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
                titles = " / ".join(dict.fromkeys(ev.title or "Untitled" for ev in evs))
                locations = list(dict.fromkeys(ev.location for ev in evs if ev.location))
                teachers = list(dict.fromkeys(ev.teacher_name for ev in evs if ev.teacher_name))
                substitutes = list(
                    dict.fromkeys(
                        ev.substitute_name for ev in evs if ev.has_substitute and ev.substitute_name
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
            click.echo("No events today.")
        click.echo()

        # ── Homework due today ────────────────────────────────────────────────
        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is not None:
            child_filter, institution_filter, session_uuid = widget_ctx

            if child:
                selected_user_ids = {
                    str(c._raw["userId"]) for c in children if c._raw and "userId" in c._raw
                }
                child_filter = [uid for uid in child_filter if uid in selected_user_ids]

            from .const import WIDGET_MIN_UDDANNELSE

            try:
                all_tasks = await client.widgets.get_mu_tasks(
                    WIDGET_MIN_UDDANNELSE, child_filter, institution_filter, week, session_uuid
                )
            except Exception as e:
                all_tasks = []
                _log.warning("Could not fetch tasks: %s", e)

            today_tasks = [
                t
                for t in all_tasks
                if t.weekday == today_weekday_da
                or (t.due_date and t.due_date.date() == today.date())
            ]

            if today_tasks:
                click.echo("## Homework Due Today")
                click.echo()
                for task in today_tasks:
                    subjects = ", ".join(
                        cls.subject_name for cls in task.classes if cls.subject_name
                    )
                    label = f"{subjects}: {task.title}" if subjects else task.title
                    status = " ✓" if task.is_completed else ""
                    click.echo(f"- {label}{status}")
                click.echo()

        # ── Unread messages ───────────────────────────────────────────────────
        try:
            unread_threads = await client.get_message_threads(filter_on="unread")
        except Exception as e:
            unread_threads = []
            _log.warning("Could not fetch unread messages: %s", e)

        if unread_threads:
            click.echo("## Unread Messages")
            click.echo()
            for thread in unread_threads:
                raw = thread._raw or {}
                participants = [p.get("name", "?") for p in raw.get("participants", [])]
                last_updated = raw.get("lastUpdatedDate", "")
                meta = []
                if participants:
                    meta.append(", ".join(participants))
                if last_updated:
                    meta.append(last_updated)
                click.echo(f"### {thread.subject}")
                if meta:
                    click.echo(f"_{' | '.join(meta)}_")
                click.echo()
                try:
                    msgs = await client.get_messages_for_thread(thread.thread_id)
                    for msg in msgs:
                        msg_raw = msg._raw or {}
                        sender = msg_raw.get("sender", {}).get("fullName", "Unknown")
                        send_date = msg_raw.get("sendDateTime", "")
                        click.echo(f"**{sender}** {send_date}".strip())
                        for line in msg.content.splitlines():
                            if line.strip():
                                click.echo(line)
                        click.echo()
                except Exception as e:
                    _log.warning("Could not fetch messages for thread %s: %s", thread.thread_id, e)
                    click.echo()


if __name__ == "__main__":
    cli()
