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

from .api_client import AulaApiClient
from .auth_flow import authenticate_and_create_client
from .config import CONFIG_FILE, DEFAULT_TOKEN_FILE, load_config, save_config
from .models import DailyOverview, Message, MessageThread, Notification, Profile
from .token_storage import FileTokenStorage
from .utils.json import to_json
from .utils.output import (
    clip,
    format_calendar_context_lines,
    format_message_lines,
    format_notification_lines,
    format_post_lines,
    format_record_lines,
    format_report_intro_lines,
    format_row,
    output_json,
    print_empty,
    print_error,
    print_heading,
)


# Decorator to run async functions within Click commands
def async_cmd(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # On Windows, use SelectorEventLoop to avoid 'Event loop closed' issues
        loop_factory = asyncio.SelectorEventLoop if sys.platform.startswith("win") else None
        return asyncio.run(func(*args, **kwargs), loop_factory=loop_factory)

    return wrapper


class WeeklySummaryProvider(enum.StrEnum):
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
@click.option(
    "--auth-method",
    type=click.Choice(["app", "token"], case_sensitive=False),
    default="app",
    envvar="AULA_AUTH_METHOD",
    help="MitID auth method: 'app' (QR/OTP) or 'token' (code token + password).",
)
@click.option(
    "--output",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    envvar="AULA_OUTPUT",
    help="Output format: 'text' (human-readable) or 'json' (machine-readable).",
)
@click.pass_context
def cli(ctx, username: str | None, verbose: int, auth_method: str, output_format: str):
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

    ctx.obj["AUTH_METHOD"] = auth_method
    ctx.obj["OUTPUT_FORMAT"] = output_format

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


async def _select_identity(identities: list[str]) -> int:
    """Prompt the user to choose between multiple MitID identities."""
    click.echo("\nMultiple identities found. Please select one:")
    for i, identity in enumerate(identities, 1):
        click.echo(f"  {i}. {identity}")
    choice = click.prompt("Select identity", type=click.IntRange(1, len(identities)), default=1)
    return choice - 1


async def _prompt_token_digits() -> str:
    return click.prompt("MitID token code (6 digits)", type=str)


async def _prompt_password() -> str:
    return click.prompt("MitID password", hide_input=True, type=str)


async def _get_client(ctx: click.Context) -> AulaApiClient:
    """Create an authenticated AulaApiClient."""
    username = get_mitid_username(ctx)
    token_storage = FileTokenStorage(DEFAULT_TOKEN_FILE)
    return await authenticate_and_create_client(
        username,
        token_storage,
        on_qr_codes=_print_qr_codes_in_terminal,
        on_login_required=_on_login_required,
        on_identity_selected=_select_identity,
        auth_method=ctx.obj.get("AUTH_METHOD", "app"),
        on_token_digits=_prompt_token_digits,
        on_password=_prompt_password,
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
        if output_json(ctx, {"status": "ok", "api_url": client.api_url}):
            return
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
            print_error(f"fetching or parsing profile data: {e}")
            return
        except Exception as e:
            print_error(f"unexpected failure: {e}")
            return

        if output_json(ctx, dict(prof)):
            return

        print_heading("Profile")
        click.echo(format_row(prof.display_name, f"ID {prof.profile_id}"))

        if prof.institution_profile_ids:
            ids = ", ".join(str(i) for i in prof.institution_profile_ids)
            click.echo(format_row("Institution profile IDs", ids))

        if prof.children:
            click.echo(f"Children ({len(prof.children)}):")
            for child in prof.children:
                click.echo(
                    f"- {format_row(child.name, f'ID {child.id}', f'Profile {child.profile_id}')}"
                )
                if child.institution_name:
                    click.echo(f"  Institution: {child.institution_name}")
        else:
            print_empty("children")


@cli.command()
@click.option("--group-id", type=int, default=None, help="Show a single group by ID.")
@click.option("--members", is_flag=True, help="List members of the group (requires --group-id).")
@click.pass_context
@async_cmd
async def groups(ctx, group_id, members):
    """List child's groups, or show group detail / members."""
    async with await _get_client(ctx) as client:
        if group_id and members:
            try:
                result = await client.get_group_members(group_id)
            except Exception as e:
                print_error(f"fetching group members: {e}")
                return

            if output_json(ctx, [dict(m) for m in result]):
                return

            if not result:
                print_empty("group members")
                return

            print_heading(f"Group {group_id} Members")
            for m in result:
                role = f" ({m.portal_role})" if m.portal_role else ""
                click.echo(format_row(m.name, f"ID {m.institution_profile_id}{role}"))
            return

        if group_id:
            try:
                group = await client.get_group(group_id)
            except Exception as e:
                print_error(f"fetching group: {e}")
                return

            if group is None:
                print_empty("group")
                return

            if output_json(ctx, dict(group)):
                return

            print_heading(f"Group: {group.name}")
            click.echo(format_row("ID", str(group.id)))
            if group.group_type:
                click.echo(format_row("Type", group.group_type))
            if group.institution_code:
                click.echo(format_row("Institution", group.institution_code))
            if group.description:
                click.echo(format_row("Description", group.description))
            return

        # List all groups for children
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        institution_codes: list[str] = []
        child_profile_ids: list[int] = []
        for child in prof.children:
            child_profile_ids.append(child.id)
            if child._raw:
                code = child._raw.get("institutionProfile", {}).get("institutionCode", "")
                if code and str(code) not in institution_codes:
                    institution_codes.append(str(code))

        try:
            result = await client.get_groups(institution_codes, child_profile_ids)
        except Exception as e:
            print_error(f"fetching groups: {e}")
            return

        if output_json(ctx, [dict(g) for g in result]):
            return

        if not result:
            print_empty("groups")
            return

        print_heading("Groups")
        for g in result:
            parts = [f"ID {g.id}"]
            if g.group_type:
                parts.append(g.group_type)
            if g.institution_code:
                parts.append(f"Inst {g.institution_code}")
            click.echo(format_row(g.name, *parts))


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
                print_error(f"fetching profile: {e}")
                return

        if ctx.obj.get("OUTPUT_FORMAT") == "json":
            results = []
            for c_id in child_ids:
                try:
                    data: DailyOverview | None = await client.get_daily_overview(c_id)
                    results.append(
                        dict(data) if data else {"child_id": c_id, "status": "unavailable"}
                    )
                except Exception as e:
                    results.append({"child_id": c_id, "error": str(e)})
            click.echo(to_json(results))
            return

        for i, c_id in enumerate(child_ids):
            try:
                data: DailyOverview | None = await client.get_daily_overview(c_id)
                if data is None:
                    click.echo(f"- {child_names.get(c_id, f'Child {c_id}')}: unavailable")
                    continue

                fallback = (
                    data.institution_profile.name if data.institution_profile else f"Child {c_id}"
                )
                name = child_names.get(c_id, fallback)
                display_name = name or fallback or f"Child {c_id}"
                status = data.status.display_name if data.status else "Unknown"
                ip = data.institution_profile
                institution = ip.institution_name if ip else None
                group = data.main_group.name if data.main_group else None

                if i == 0:
                    print_heading("Overview")

                click.echo(format_row(display_name, status))
                if institution or group:
                    click.echo(f"  {' / '.join(filter(None, [institution, group]))}")

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
                print_error(f"fetching overview for child {c_id}: {e}")


@cli.command()
@click.option("--limit", type=int, default=5, help="Number of threads to fetch.")
@click.option("--unread", is_flag=True, default=False, help="Only show unread message threads.")
@click.option("--search", type=str, default=None, help="Search messages for the given text.")
@click.option("--folders", is_flag=True, default=False, help="List message folders.")
@click.pass_context
@async_cmd
async def messages(ctx, limit, unread, search, folders):
    """Fetch the latest message threads and their messages."""
    async with await _get_client(ctx) as client:
        if folders:
            try:
                folder_list = await client.get_message_folders()
            except Exception as e:
                print_error(f"fetching message folders: {e}")
                return

            if output_json(ctx, [dict(f) for f in folder_list]):
                return

            if not folder_list:
                print_empty("message folders")
                return

            print_heading("Message Folders")
            for f in folder_list:
                click.echo(format_row(f.name, f"ID {f.id}"))
            return

        if search:
            try:
                prof: Profile = await client.get_profile()
            except Exception as e:
                print_error(f"fetching profile: {e}")
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
                print_error(f"searching messages: {e}")
                return

            if output_json(ctx, [dict(m) for m in results]):
                return

            if not results:
                print_empty("messages")
                return

            print_heading(f'Messages: "{search}"')

            for i, msg in enumerate(results):
                msg_raw = msg._raw or {}
                sender = msg_raw.get("sender", {}).get("fullName", "Unknown")
                send_date = msg_raw.get("sendDateTime", "")
                subject = msg_raw.get("threadSubject", "")

                for line in format_message_lines(subject, sender, send_date, msg.content):
                    click.echo(line)

                if i < len(results) - 1:
                    click.echo()
            return

        try:
            filter_on = "unread" if unread else None
            threads: list[MessageThread] = await client.get_message_threads(filter_on=filter_on)
            threads = threads[:limit]
        except Exception as e:
            print_error(f"fetching message threads: {e}")
            return

        if ctx.obj.get("OUTPUT_FORMAT") == "json":
            json_threads = []
            for thread in threads:
                t = dict(thread)
                try:
                    messages_list: list[Message] = await client.get_messages_for_thread(
                        thread.thread_id
                    )
                    t["messages"] = [dict(m) for m in messages_list]
                except Exception:
                    t["messages"] = []
                json_threads.append(t)
            click.echo(to_json(json_threads))
            return

        filter_label = "unread" if unread else "latest"
        print_heading(f"Message threads: {filter_label}")

        if not threads:
            print_empty("message threads")
            return

        for i, thread in enumerate(threads):
            raw = thread._raw or {}
            participants = [p.get("name", "?") for p in raw.get("participants", [])]
            last_updated = raw.get("lastUpdatedDate", "")

            # Thread header
            click.echo(clip(thread.subject))
            meta_parts = []
            if participants:
                meta_parts.append(", ".join(participants))
            if last_updated:
                meta_parts.append(last_updated)
            if meta_parts:
                click.echo(f"  {clip(' | '.join(meta_parts))}")

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
                        message_title = msg_raw.get("threadSubject", "")
                        for line in format_message_lines(
                            message_title,
                            sender,
                            send_date,
                            msg.content,
                            fallback_title=thread.subject,
                            include_title=False,
                        ):
                            click.echo(f"{line}")
            except Exception as e:
                print_error(str(e))

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
        institution_names: dict[str, str] = {}
        children_ids: list[int] = []
        institution_codes: list[str] = []
        prof: Profile | None = None
        try:
            prof = await client.get_profile()
            for child in prof.children:
                children_ids.append(child.id)
                if not child._raw:
                    continue
                institution = child._raw.get("institutionProfile", {})
                code = institution.get("institutionCode")
                name = institution.get("institutionName")
                if code and name and str(code) not in institution_names:
                    institution_names[str(code)] = str(name)
                if code and str(code) not in institution_codes:
                    institution_codes.append(str(code))
        except Exception:
            # Keep notifications usable even if profile lookup fails.
            institution_names = {}

        try:
            items: list[Notification] = await client.get_notifications_for_active_profile(
                children_ids=children_ids,
                institution_codes=institution_codes,
                offset=offset,
                limit=limit,
                module=module,
            )
        except Exception as e:
            print_error(f"fetching notifications: {e}")
            return

        if output_json(ctx, [dict(item) for item in items]):
            return

        if not items:
            print_empty("notifications")
            return

        album_names: dict[int, str] = {}
        new_media_album_ids = {
            item.album_id
            for item in items
            if item.event_type == "NewMedia" and item.album_id is not None
        }
        if new_media_album_ids and prof and prof.institution_profile_ids:
            try:
                albums = await client.get_gallery_albums(prof.institution_profile_ids)
                album_names = {
                    a["id"]: a["title"]
                    for a in albums
                    if isinstance(a.get("id"), int) and isinstance(a.get("title"), str)
                }
            except Exception:
                pass

        heading = f"Notifications ({len(items)})"
        print_heading(heading)

        # Group by event type and show summary
        groups: dict[str, list[Notification]] = {}
        for item in items:
            key = item.event_type or "Unknown"
            groups.setdefault(key, []).append(item)

        click.echo("Summary:")
        for event_type, group_items in sorted(groups.items(), key=lambda x: -len(x[1])):
            click.echo(f"  {event_type}: {len(group_items)}")
        click.echo()

        for event_type, group_items in sorted(groups.items(), key=lambda x: -len(x[1])):
            click.echo(f"── {event_type} ({len(group_items)}) ──")
            for i, item in enumerate(group_items):
                for line in format_notification_lines(
                    item, institution_names=institution_names, album_names=album_names
                ):
                    click.echo(line)

                if i < len(group_items) - 1:
                    click.echo()
            click.echo()


@cli.command()
@click.option(
    "--institution-profile-id",
    multiple=True,
    type=int,
    help="Filter events by specific child ID(s).",
)
@click.option("--event-id", type=int, default=None, help="Show a single event by ID.")
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
async def calendar(ctx, institution_profile_id, event_id, start_date, end_date):
    """Fetch calendar events for children."""
    async with await _get_client(ctx) as client:
        if event_id:
            try:
                event = await client.get_calendar_event(event_id)
            except Exception as e:
                print_error(f"fetching calendar event: {e}")
                return

            if event is None:
                print_empty("calendar event")
                return

            if output_json(ctx, event):
                return

            print_heading(f"Event: {event.get('title', event_id)}")
            for key in ["id", "title", "startDateTime", "endDateTime", "type", "location"]:
                if key in event and event[key]:
                    click.echo(format_row(key, str(event[key])))
            return

        institution_profile_ids = list(institution_profile_id)

        if not institution_profile_ids:
            try:
                prof = await client.get_profile()
                institution_profile_ids = prof.institution_profile_ids
            except Exception as e:
                print_error(f"fetching profile to get child IDs: {e}")
                return

        if not institution_profile_ids:
            print_empty("institution profile IDs")
            return

        try:
            events = await client.get_calendar_events(institution_profile_ids, start_date, end_date)
        except Exception as e:
            print_error(f"fetching calendar events: {e}")
            return

        if output_json(ctx, [dict(ev) for ev in events]):
            return

        print_heading("Calendar events")
        for line in format_calendar_context_lines(
            start_date,
            end_date,
            profile_count=len(institution_profile_ids),
        ):
            click.echo(line)

        if not events:
            print_empty("calendar events")
            return

        from .utils.table import build_calendar_table, print_calendar_table

        table_data = build_calendar_table(events)
        print_calendar_table(table_data)


@cli.command("important-dates")
@click.option("--limit", type=int, default=10, help="Maximum number of dates to fetch.")
@click.pass_context
@async_cmd
async def important_dates(ctx, limit):
    """Fetch upcoming important dates."""
    async with await _get_client(ctx) as client:
        try:
            dates = await client.get_important_dates(limit=limit)
        except Exception as e:
            print_error(f"fetching important dates: {e}")
            return

        if output_json(ctx, dates):
            return

        if not dates:
            print_empty("important dates")
            return

        print_heading("Important Dates")
        for d in dates:
            title = d.get("title", "Untitled")
            date_str = d.get("startDateTime", d.get("date", ""))
            click.echo(format_row(title, date_str))


@cli.command()
@click.option(
    "--group-id",
    type=int,
    default=None,
    help="Filter birthdays by group ID.",
)
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=datetime.datetime.now(ZoneInfo("Europe/Copenhagen")),
    help="Start date (YYYY-MM-DD). Defaults to today.",
)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=(datetime.datetime.now(ZoneInfo("Europe/Copenhagen")) + datetime.timedelta(days=30)),
    help="End date (YYYY-MM-DD). Defaults to 30 days from today.",
)
@click.pass_context
@async_cmd
async def birthdays(ctx, group_id, start_date, end_date):
    """Fetch birthday events."""
    start = start_date.strftime("%Y-%m-%d")
    end = end_date.strftime("%Y-%m-%d")

    async with await _get_client(ctx) as client:
        if group_id:
            try:
                result = await client.get_birthday_events_for_group(group_id, start, end)
            except Exception as e:
                print_error(f"fetching birthdays for group: {e}")
                return
        else:
            try:
                prof: Profile = await client.get_profile()
            except Exception as e:
                print_error(f"fetching profile: {e}")
                return

            institution_codes: list[str] = []
            for child in prof.children:
                if child._raw:
                    code = child._raw.get("institutionProfile", {}).get("institutionCode", "")
                    if code and str(code) not in institution_codes:
                        institution_codes.append(str(code))

            try:
                result = await client.get_birthday_events(institution_codes, start, end)
            except Exception as e:
                print_error(f"fetching birthdays: {e}")
                return

        if output_json(ctx, result):
            return

        if not result:
            print_empty("birthdays")
            return

        print_heading("Birthdays")
        for item in result:
            name = item.get("name", "Unknown")
            bday = item.get("birthday", item.get("date", ""))
            click.echo(format_row(name, bday))


@cli.command()
@click.option(
    "--institution-profile-id",
    multiple=True,
    type=int,
    help="Filter posts by specific institution profile ID(s).",
)
@click.option("--post-id", type=int, default=None, help="Show a single post by ID.")
@click.option("--comments", is_flag=True, help="Show comments on the post (requires --post-id).")
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
async def posts(ctx, institution_profile_id, post_id, comments, limit, page):
    """Fetch posts from Aula."""
    async with await _get_client(ctx) as client:
        if post_id:
            try:
                post = await client.get_post(post_id)
            except Exception as e:
                print_error(f"fetching post: {e}")
                return

            if post is None:
                print_empty("post")
                return

            post_data = dict(post)
            comment_list = []
            if comments:
                try:
                    comment_list = await client.get_comments("post", post_id)
                    post_data["comments"] = [dict(c) for c in comment_list]
                except Exception as e:
                    print_error(f"fetching comments: {e}")

            if output_json(ctx, post_data):
                return

            date_str = post.timestamp.strftime("%Y-%m-%d %H:%M") if post.timestamp else ""
            for line in format_post_lines(
                title=post.title,
                author=post.owner.full_name,
                date=date_str,
                body=post.content,
                attachments_count=len(post.attachments),
            ):
                click.echo(line)

            if comment_list:
                click.echo()
                print_heading("Comments")
                for c in comment_list:
                    click.echo(format_row(c.creator_name, c.created_at))
                    click.echo(f"  {c.content}")
                    click.echo()
            return

        institution_profile_ids = list(institution_profile_id)

        if not institution_profile_ids:
            try:
                prof = await client.get_profile()
                institution_profile_ids = prof.institution_profile_ids
            except Exception as e:
                print_error(f"fetching profile: {e}")
                return

        try:
            posts_list = await client.get_posts(
                page=page,
                limit=limit,
                institution_profile_ids=institution_profile_ids,
            )

            if output_json(ctx, [dict(p) for p in posts_list]):
                return

            if not posts_list:
                print_empty("posts")
                return

            print_heading("Posts")

            for i, post in enumerate(posts_list):
                date_str = post.timestamp.strftime("%Y-%m-%d %H:%M") if post.timestamp else ""

                for line in format_post_lines(
                    title=post.title,
                    author=post.owner.full_name,
                    date=date_str,
                    body=post.content,
                    attachments_count=len(post.attachments),
                ):
                    click.echo(line)

                if i < len(posts_list) - 1:
                    click.echo()

        except Exception as e:
            print_error(f"fetching posts: {e}")
            return


@cli.command("widgets")
@click.pass_context
@async_cmd
async def widgets(ctx):
    """List available widgets configured for the current user."""
    async with await _get_client(ctx) as client:
        try:
            widget_list = await client.get_widgets()
        except Exception as e:
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
                click.echo(line)
            click.echo()


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
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            return
        child_filter, institution_filter, session_uuid = widget_ctx

        from .const import WIDGET_MIN_UDDANNELSE_TASKS

        try:
            opgaver = await client.widgets.get_mu_tasks(
                WIDGET_MIN_UDDANNELSE_TASKS,
                child_filter,
                institution_filter,
                week,
                session_uuid,
            )
        except Exception as e:
            print_error(f"fetching tasks: {e}")
            return

        if output_json(ctx, [dict(t) for t in opgaver]):
            return

        print_heading(f"Min Uddannelse tasks [{week}]")

        if not opgaver:
            print_empty("tasks")
        else:
            for i, task in enumerate(opgaver):
                classes = ", ".join(
                    f"{cls.name} ({cls.subject_name})" if cls.subject_name else cls.name
                    for cls in task.classes
                )
                course = task.course.name if task.course else ""
                for line in format_record_lines(
                    title=task.title,
                    properties=[
                        ("Student", task.student_name),
                        ("Day", task.weekday),
                        ("Type", task.task_type),
                        ("Classes", classes),
                        ("Course", course),
                    ],
                ):
                    click.echo(line)
                if i < len(opgaver) - 1:
                    click.echo()


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
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
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
            print_error(f"fetching weekly plans: {e}")
            return

        if output_json(ctx, [dict(p) for p in personer]):
            return

        if not personer:
            print_empty("weekly plans")
            return

        print_heading(f"Min Uddannelse weekly plans [{week}]")

        rendered = 0
        for person in personer:
            for inst in person.institutions:
                for letter in inst.letters:
                    rendered += 1
                    for line in format_record_lines(
                        title=f"{person.name} [{letter.group_name}]",
                        properties=[
                            ("Institution", inst.name),
                            ("Week", str(letter.week_number)),
                        ],
                        body_lines=html_to_plain(letter.content_html).splitlines(),
                        body_label="Body",
                        empty_body_text="(no weekly plan body)",
                    ):
                        click.echo(line)
                    click.echo()

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
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
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
            print_error(f"fetching profile context: {e}")
            return

        from .utils.html import html_to_plain

        if ctx.obj.get("OUTPUT_FORMAT") == "json":
            all_appointments = []
            for child in prof.children:
                if not child._raw or "userId" not in child._raw:
                    continue
                child_id = str(child._raw["userId"])
                try:
                    appointments = await client.widgets.get_easyiq_weekplan(
                        week, session_uuid, institution_filter, child_id
                    )
                    all_appointments.extend(dict(a) for a in appointments)
                except Exception:
                    continue
            click.echo(to_json(all_appointments))
            return

        print_heading(f"EasyIQ weekly plan [{week}]")
        rendered = 0

        for child in prof.children:
            if not child._raw or "userId" not in child._raw:
                continue
            child_id = str(child._raw["userId"])

            try:
                appointments = await client.widgets.get_easyiq_weekplan(
                    week, session_uuid, institution_filter, child_id
                )
            except Exception as e:
                print_error(f"fetching EasyIQ weekplan for {child.name}: {e}")
                continue

            for appt in appointments:
                rendered += 1
                for line in format_record_lines(
                    title=appt.title,
                    properties=[
                        ("Child", child.name),
                        ("Start", appt.start),
                        ("End", appt.end),
                    ],
                    body_lines=html_to_plain(appt.description).splitlines()
                    if appt.description
                    else [],
                    body_label="Body",
                    empty_body_text="(no description)",
                ):
                    click.echo(line)
                click.echo()

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
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
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
            print_error(f"fetching profile context: {e}")
            return

        from .utils.html import html_to_plain

        if ctx.obj.get("OUTPUT_FORMAT") == "json":
            all_homework = []
            for child in prof.children:
                if not child._raw or "userId" not in child._raw:
                    continue
                child_id = str(child._raw["userId"])
                try:
                    homework = await client.widgets.get_easyiq_homework(
                        week, session_uuid, institution_filter, child_id
                    )
                    all_homework.extend(dict(hw) for hw in homework)
                except Exception:
                    continue
            click.echo(to_json(all_homework))
            return

        print_heading(f"EasyIQ homework [{week}]")
        rendered = 0

        for child in prof.children:
            if not child._raw or "userId" not in child._raw:
                continue
            child_id = str(child._raw["userId"])

            try:
                homework = await client.widgets.get_easyiq_homework(
                    week, session_uuid, institution_filter, child_id
                )
            except Exception as e:
                print_error(f"fetching EasyIQ homework for {child.name}: {e}")
                continue

            for hw in homework:
                rendered += 1
                status = "Completed" if hw.is_completed else "Pending"
                for line in format_record_lines(
                    title=hw.title,
                    properties=[
                        ("Child", child.name),
                        ("Status", status),
                        ("Subject", hw.subject),
                        ("Due", hw.due_date),
                    ],
                    body_lines=html_to_plain(hw.description).splitlines() if hw.description else [],
                    body_label="Body",
                    empty_body_text="(no description)",
                ):
                    click.echo(line)
                click.echo()

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
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        child_filter = [
            str(child._raw["userId"])
            for child in prof.children
            if child._raw and "userId" in child._raw
        ]
        if not child_filter:
            print_empty("child user IDs")
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
            print_error(f"fetching profile context: {e}")
            return

        try:
            students = await client.widgets.get_meebook_weekplan(
                child_filter, institution_filter, week, session_uuid
            )
        except Exception as e:
            print_error(f"fetching Meebook weekplan: {e}")
            return

        if output_json(ctx, [dict(s) for s in students]):
            return

        if not students:
            print_empty("weekly plans")
            return

        from .utils.html import html_to_plain

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
                        click.echo(line)
                    click.echo()

        if rendered == 0:
            print_empty("weekly plans")


@cli.command("momo:forløb")
@click.pass_context
@async_cmd
async def momo_course(ctx):
    """Fetch MoMo courses (forløb) for children."""
    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        children = [
            str(child._raw["userId"])
            for child in prof.children
            if child._raw and "userId" in child._raw
        ]
        if not children:
            print_empty("child user IDs")
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
            print_error(f"fetching profile context: {e}")
            return

        try:
            users_with_courses = await client.widgets.get_momo_courses(
                children, institutions, session_uuid
            )
        except Exception as e:
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
                    click.echo(line)
                click.echo()

        if rendered == 0:
            print_empty("courses")


@cli.command("momo:huskeliste")
@click.pass_context
@async_cmd
async def momo_reminders(ctx):
    """Fetch MoMo reminders (huskelisten) for children."""
    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        children = [
            str(child._raw["userId"])
            for child in prof.children
            if child._raw and "userId" in child._raw
        ]
        if not children:
            print_empty("child user IDs")
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
            print_error(f"fetching profile context: {e}")
            return

        today = datetime.date.today()
        from_date = today.isoformat()
        due_no_later_than = (today + datetime.timedelta(days=7)).isoformat()

        try:
            users = await client.widgets.get_momo_reminders(
                children, institutions, session_uuid, from_date, due_no_later_than
            )
        except Exception as e:
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
                    click.echo(line)
                click.echo()

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
                    click.echo(line)
                click.echo()

        if rendered == 0:
            print_empty("reminders")


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
        is_json = ctx.obj.get("OUTPUT_FORMAT") == "json"
        if not is_json:
            print_heading("Download images")
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
        on_progress = click.echo if not is_json else lambda _msg: None

        if source in ("all", "gallery"):
            if not is_json:
                click.echo("Gallery")
            dl, sk = await download_gallery_images(
                client,
                institution_profile_ids,
                output_path,
                cutoff,
                tag_list,
                on_progress=on_progress,
            )
            if not is_json:
                click.echo(f"  Downloaded: {dl}")
                click.echo(f"  Skipped: {sk}")
                click.echo()
            total_downloaded += dl
            total_skipped += sk

        if source in ("all", "posts"):
            if not is_json:
                click.echo("Posts")
            dl, sk = await download_post_images(
                client,
                institution_profile_ids,
                output_path,
                cutoff,
                on_progress=on_progress,
            )
            if not is_json:
                click.echo(f"  Downloaded: {dl}")
                click.echo(f"  Skipped: {sk}")
                click.echo()
            total_downloaded += dl
            total_skipped += sk

        if source in ("all", "messages"):
            if not is_json:
                click.echo("Messages")
            dl, sk = await download_message_images(
                client,
                children_inst_ids,
                institution_codes,
                output_path,
                cutoff,
                on_progress=on_progress,
            )
            if not is_json:
                click.echo(f"  Downloaded: {dl}")
                click.echo(f"  Skipped: {sk}")
                click.echo()
            total_downloaded += dl
            total_skipped += sk

        if output_json(ctx, {"downloaded": total_downloaded, "skipped": total_skipped}):
            return

        click.echo("Total")
        click.echo(f"  Downloaded: {total_downloaded}")
        click.echo(f"  Skipped: {total_skipped}")


@cli.command("library:status")
@click.pass_context
@async_cmd
async def library_status(ctx):
    """Fetch library loans and reservations for children."""
    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
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
                click.echo(line)
            click.echo()

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
                click.echo(line)
            click.echo()

        for reservation in status.reservations:
            rendered += 1
            for line in format_record_lines(
                title=str(reservation),
                properties=[("Category", "Reservation")],
            ):
                click.echo(line)
            click.echo()

        if rendered == 0:
            print_empty("loans or reservations")


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

    is_json = ctx.obj.get("OUTPUT_FORMAT") == "json"
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
                click.echo(line)
            click.echo()

        # ── Calendar events ──────────────────────────────────────────────────
        child_inst_ids = [c.id for c in children]
        try:
            events = await client.get_calendar_events(child_inst_ids, week_start, week_end)
        except Exception as e:
            events = []
            logging.getLogger(__name__).warning("Could not fetch calendar events: %s", e)

        if json_result is not None:
            json_result["calendar_events"] = [dict(ev) for ev in events]

        if not is_json:
            click.echo("Calendar events")
            click.echo()
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
                    click.echo(day_label)
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
                print_empty("calendar events")
                click.echo()

        # ── Unread messages ──────────────────────────────────────────────────
        try:
            unread_threads = await client.get_message_threads(filter_on="unread")
        except Exception as e:
            unread_threads = []
            _log.warning("Could not fetch unread messages: %s", e)

        if json_result is not None:
            json_result["unread_messages"] = [dict(t) for t in unread_threads]

        if not is_json and unread_threads:
            click.echo("Unread messages")
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
                click.echo(thread.subject)
                if meta:
                    click.echo(f"  Meta: {' | '.join(meta)}")
                click.echo()
                try:
                    msgs = await client.get_messages_for_thread(thread.thread_id)
                    for msg in msgs:
                        msg_raw = msg._raw or {}
                        sender = msg_raw.get("sender", {}).get("fullName", "Unknown")
                        send_date = msg_raw.get("sendDateTime", "")
                        click.echo(f"Author: {sender}")
                        if send_date:
                            click.echo(f"Date: {send_date}")
                        for line in msg.content.splitlines():
                            if line.strip():
                                click.echo(line)
                        click.echo()
                except Exception as e:
                    _log.warning("Could not fetch messages for thread %s: %s", thread.thread_id, e)
                    click.echo()

        if not enabled:
            if json_result is not None:
                click.echo(to_json(json_result))
            return  # nothing to fetch beyond calendar

        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is None:
            if json_result is not None:
                click.echo(to_json(json_result))
                return
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
            from .const import WIDGET_MIN_UDDANNELSE_TASKS

            try:
                tasks = await client.widgets.get_mu_tasks(
                    WIDGET_MIN_UDDANNELSE_TASKS,
                    child_filter,
                    institution_filter,
                    week,
                    session_uuid,
                )
            except Exception as e:
                tasks = []
                _log.warning("Could not fetch MU tasks: %s", e)

            if json_result is not None:
                json_result["mu_tasks"] = [dict(t) for t in tasks]

            if not is_json:
                click.echo("Homework & tasks (Min Uddannelse)")
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
                    print_empty("tasks")
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

            if json_result is not None:
                json_result["mu_ugeplan"] = [dict(p) for p in mu_persons]

            if not is_json and mu_persons:
                click.echo("Weekly letter (Min Uddannelse ugeplan)")
                click.echo()
                for person in mu_persons:
                    for inst in person.institutions:
                        for letter in inst.letters:
                            click.echo(f"{person.name} - {letter.group_name} ({inst.name})")
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

            if json_result is not None:
                json_result["meebook_weekplan"] = [dict(s) for s in meebook_students]

            if not is_json and meebook_students:
                click.echo("Weekly plan (Meebook)")
                click.echo()
                for student in meebook_students:
                    click.echo(student.name)
                    click.echo()
                    for day in student.week_plan:
                        if not day.tasks:
                            continue
                        click.echo(day.date)
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
            easyiq_appointments: list[dict] = []
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

                easyiq_appointments.extend(dict(a) for a in appointments)

                if not is_json:
                    if not easyiq_any:
                        click.echo("Weekly plan (EasyIQ)")
                        click.echo()
                        easyiq_any = True

                    click.echo(c.name)
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

            if json_result is not None:
                json_result["easyiq_weekplan"] = easyiq_appointments

        # ── EasyIQ – Homework ──────────────────────────────────────────────────
        if WeeklySummaryProvider.EASYIQ_HOMEWORK in enabled:
            easyiq_hw_items: list[dict] = []
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

                easyiq_hw_items.extend(dict(hw) for hw in homework)

                if not is_json:
                    if not easyiq_hw_any:
                        click.echo("Homework (EasyIQ)")
                        click.echo()
                        easyiq_hw_any = True

                    click.echo(c.name)
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

            if json_result is not None:
                json_result["easyiq_homework"] = easyiq_hw_items

        if json_result is not None:
            click.echo(to_json(json_result))


def _format_time(raw: str | None) -> str:
    """Extract HH:mm from a raw time string (may be ISO datetime or HH:mm)."""
    if not raw:
        return "?"
    return raw.split("T")[-1][:5]


def _format_time_or_none(raw: str | None) -> str | None:
    """Extract HH:mm or return None."""
    if not raw:
        return None
    return raw.split("T")[-1][:5]


def _prompt_time(label: str, default: str | None = None) -> str | None:
    """Prompt for a time in HH:mm format. Empty input returns None (keep current)."""
    hint = f" [{default}]" if default else ""
    while True:
        value = click.prompt(
            f"  {label}{hint}",
            default=default or "",
            show_default=False,
        )
        value = value.strip()
        if not value:
            return None
        try:
            datetime.datetime.strptime(value, "%H:%M")
            return value
        except ValueError:
            click.echo("    Invalid format. Use HH:mm (e.g., 08:00, 15:30)")


def _resolve_pickup(
    all_names: list[str],
    exit_with: str | None,
) -> tuple[str | None, bool]:
    """Resolve --exit-with against the pickup list.

    Returns (resolved_name_or_None, ok).
    """
    if exit_with is None:
        return None, True
    if exit_with.isdigit():
        idx = int(exit_with) - 1
        if 0 <= idx < len(all_names):
            return all_names[idx], True
        return None, False
    return exit_with, True


def _strip_relation(name: str | None) -> str | None:
    """Return the name as-is — the Aula API expects the relation suffix included."""
    return name


@cli.command("update-presence")
@click.option(
    "--date",
    "target_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Date to update (YYYY-MM-DD). Defaults to today.",
)
@click.option(
    "--entry-time",
    type=str,
    default=None,
    help="Arrival time in HH:mm format (e.g., 08:00).",
)
@click.option(
    "--exit-time",
    type=str,
    default=None,
    help="Departure/pickup time in HH:mm format (e.g., 16:30).",
)
@click.option(
    "--exit-with",
    type=str,
    default=None,
    help="Pickup person name (or number from the pickup responsibles list).",
)
@click.option(
    "--comment",
    type=str,
    default=None,
    help="Optional daily comment/remark.",
)
@click.option(
    "--child",
    "child_ids",
    type=int,
    multiple=True,
    help="Specific child institution profile ID(s). Omit to update all children.",
)
@click.option(
    "--repeat",
    "repeat_pattern",
    type=click.Choice(["Never", "Weekly", "Every2Weeks"], case_sensitive=False),
    default=None,
    help="Repeat pattern for the template.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt.",
)
@click.pass_context
@async_cmd
async def update_presence(
    ctx, target_date, entry_time, exit_time, exit_with, comment, child_ids, repeat_pattern, yes
):
    """Update pickup/drop-off times for multiple children at once.

    When called without arguments, runs interactively: shows the current state
    for all children, then prompts for date, times, pickup person, etc.

    When called with arguments, applies them directly (with confirmation).

    Examples:

      aula update-presence

      aula update-presence --exit-time 15:00 --exit-with "Mom" -y

      aula update-presence --date 2026-03-10 --entry-time 08:00 --exit-time 14:00
    """
    tz = ZoneInfo("Europe/Copenhagen")
    now = datetime.datetime.now(tz)
    interactive = not any([entry_time, exit_time, exit_with, comment, child_ids, target_date])

    # Validate time format for CLI-provided values
    for label, value in [("entry-time", entry_time), ("exit-time", exit_time)]:
        if value:
            try:
                datetime.datetime.strptime(value, "%H:%M")
            except ValueError:
                print_error(f"--{label} must be in HH:mm format, got: {value}")
                return

    target = target_date.date() if target_date else now.date()

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        # Determine which children to update
        if child_ids:
            children = [c for c in prof.children if c.id in child_ids]
            if not children:
                print_error(f"no children found with IDs: {list(child_ids)}")
                return
        else:
            children = prof.children

        institution_profile_ids = [c.id for c in children]

        # Fetch current state
        _log = logging.getLogger(__name__)
        overviews: dict[int, DailyOverview] = {}
        pickup_data = []
        templates = []

        for c in children:
            try:
                ov = await client.get_daily_overview(c.id)
                if ov:
                    overviews[c.id] = ov
            except Exception as e:
                _log.warning("Could not fetch daily overview for %s: %s", c.name, e)

        try:
            pickup_data = await client.get_pickup_responsibles(institution_profile_ids)
        except Exception as e:
            _log.warning("Could not fetch pickup responsibles: %s", e)
        import contextlib

        with contextlib.suppress(Exception):
            templates = await client.get_presence_templates(institution_profile_ids, target, target)

        # Build lookup: child_id -> DayTemplate for the target date
        current_by_child: dict = {}
        for tmpl in templates:
            if tmpl.institution_profile:
                for dt in tmpl.day_templates:
                    if dt.by_date and dt.by_date[:10] == target.isoformat():
                        current_by_child[tmpl.institution_profile.id] = dt

        # Show current state
        click.echo()
        print_heading(f"Current state ({target.isoformat()})")
        click.echo()
        for c in children:
            ov = overviews.get(c.id)
            tmpl = current_by_child.get(c.id)

            status_str = ov.status.danish_name if ov and ov.status else "?"
            check_in = _format_time(ov.check_in_time) if ov and ov.check_in_time else "-"
            check_out = _format_time(ov.check_out_time) if ov and ov.check_out_time else "-"
            planned_entry = (
                _format_time(tmpl.entry_time)
                if tmpl
                else _format_time(ov.entry_time if ov else None)
            )
            planned_exit = (
                _format_time(tmpl.exit_time) if tmpl else _format_time(ov.exit_time if ov else None)
            )
            cur_who = tmpl.exit_with if tmpl else (ov.exit_with if ov else None)
            cur_comment = tmpl.comment if tmpl else (ov.comment if ov else None)
            location = ov.location if ov and ov.location else None

            click.echo(f"  {c.name}")
            click.echo(f"    Status:      {status_str}")
            if location:
                click.echo(f"    Location:    {location}")
            click.echo(f"    Checked in:  {check_in}")
            click.echo(f"    Checked out: {check_out}")
            click.echo(f"    Planned:     {planned_entry} - {planned_exit}")
            if cur_who:
                click.echo(f"    Pickup by:   {cur_who}")
            if cur_comment:
                click.echo(f"    Comment:     {cur_comment}")
            click.echo()

        # Build merged pickup person list
        all_names: list[str] = []
        seen: set[str] = set()
        for pr in pickup_data:
            for person in pr.persons:
                label = person.name
                if person.relation:
                    label = f"{person.name} ({person.relation})"
                if label not in seen:
                    seen.add(label)
                    all_names.append(label)

        # --- Interactive mode: prompt for everything ---
        if interactive:
            # Date
            date_input = click.prompt(
                "  Date",
                default=target.isoformat(),
            ).strip()
            try:
                target = datetime.date.fromisoformat(date_input)
            except ValueError:
                print_error(f"invalid date: {date_input}")
                return

            # Re-fetch templates if the date changed
            if date_input != now.date().isoformat():
                current_by_child.clear()
                try:
                    templates = await client.get_presence_templates(
                        institution_profile_ids, target, target
                    )
                    for tmpl in templates:
                        if tmpl.institution_profile:
                            for dt in tmpl.day_templates:
                                if dt.by_date and dt.by_date[:10] == target.isoformat():
                                    current_by_child[tmpl.institution_profile.id] = dt
                except Exception:
                    pass

            # Pick a representative current state for defaults
            first_tmpl = next(
                (current_by_child.get(c.id) for c in children if current_by_child.get(c.id)),
                None,
            )
            first_ov = next(
                (overviews.get(c.id) for c in children if overviews.get(c.id)),
                None,
            )
            default_entry = _format_time_or_none(
                (first_tmpl.entry_time if first_tmpl else None)
                or (first_ov.entry_time if first_ov else None)
            )
            default_exit = _format_time_or_none(
                (first_tmpl.exit_time if first_tmpl else None)
                or (first_ov.exit_time if first_ov else None)
            )

            click.echo()
            entry_time = _prompt_time("Entry time", default=default_entry)
            exit_time = _prompt_time("Exit time", default=default_exit)

            if not entry_time and not exit_time:
                click.echo("  No changes specified.")
                return

            # Pickup person
            click.echo()
            if all_names:
                click.echo("  Pickup responsibles:")
                for i, name in enumerate(all_names, 1):
                    click.echo(f"    {i}. {name}")
                click.echo("    0. (keep current)")
                click.echo()
                choice = click.prompt("  Pick a person", type=int, default=0)
                if choice > 0:
                    if 1 <= choice <= len(all_names):
                        exit_with = all_names[choice - 1]
                    else:
                        print_error(f"invalid choice {choice} (1-{len(all_names)})")
                        return

            # Comment
            comment_input = click.prompt("  Comment", default="", show_default=False).strip()
            if comment_input:
                comment = comment_input

            # Repeat
            click.echo()
            click.echo("  Repeat: 0=Never  1=Weekly  2=Every 2 weeks")
            repeat_choice = click.prompt("  Repeat", type=int, default=0)
            repeat_pattern = ["Never", "Weekly", "Every2Weeks"][min(repeat_choice, 2)]

            click.echo()

        # --- Resolve exit_with for non-interactive mode ---
        if not interactive:
            resolved, ok = _resolve_pickup(all_names, exit_with)
            if not ok:
                print_error(f"--exit-with {exit_with} is out of range (1-{len(all_names)})")
                return
            if resolved is not None:
                exit_with = resolved
            elif exit_with is None and all_names and not yes:
                # Prompt for pickup person
                click.echo("  Pickup responsibles:")
                for i, name in enumerate(all_names, 1):
                    click.echo(f"    {i}. {name}")
                click.echo("    0. (keep current)")
                click.echo()
                choice = click.prompt("  Pick a person", type=int, default=0)
                if choice > 0:
                    if 1 <= choice <= len(all_names):
                        exit_with = all_names[choice - 1]
                    else:
                        print_error(f"invalid choice {choice} (1-{len(all_names)})")
                        return

        api_exit_with = _strip_relation(exit_with)
        if repeat_pattern is None:
            repeat_pattern = "Never"

        # Show planned changes
        print_heading(f"Changes for {target.isoformat()}")
        click.echo()

        click.echo(f"  {'Child':<30s}  {'Current':<25s}    {'New'}")
        click.echo(f"  {'-' * 30}  {'-' * 25}    {'-' * 25}")

        for c in children:
            current = current_by_child.get(c.id)
            ov = overviews.get(c.id)
            cur_entry = (current.entry_time if current else None) or (ov.entry_time if ov else None)
            cur_exit = (current.exit_time if current else None) or (ov.exit_time if ov else None)
            cur_who = (current.exit_with if current else None) or (ov.exit_with if ov else None)

            new_entry = entry_time or _format_time(cur_entry)
            new_exit = exit_time or _format_time(cur_exit)
            new_who = api_exit_with if api_exit_with is not None else cur_who

            current_str = f"{_format_time(cur_entry)}-{_format_time(cur_exit)}"
            if cur_who:
                current_str += f" ({cur_who})"

            new_str = f"{new_entry}-{new_exit}"
            if new_who:
                new_str += f" ({new_who})"

            click.echo(f"  {c.name:<30s}  {current_str:<25s} -> {new_str}")

        click.echo()

        if repeat_pattern.lower() != "never":
            click.echo(f"  Repeat: {repeat_pattern}")
        if comment:
            click.echo(f"  Comment: {comment}")
            click.echo()

        if not yes and not click.confirm("Apply these changes?"):
            click.echo("Cancelled.")
            return

        # Apply updates
        success_count = 0
        for c in children:
            current = current_by_child.get(c.id)
            ov = overviews.get(c.id)
            cur_entry = (current.entry_time if current else None) or (ov.entry_time if ov else None)
            cur_exit = (current.exit_time if current else None) or (ov.exit_time if ov else None)
            cur_who = (current.exit_with if current else None) or (ov.exit_with if ov else None)
            template_id = current.id if current else None

            final_entry = entry_time or (_format_time(cur_entry) if cur_entry else "08:00")
            final_exit = exit_time or (_format_time(cur_exit) if cur_exit else "16:00")
            final_who = api_exit_with if api_exit_with is not None else cur_who

            try:
                await client.update_presence_template(
                    institution_profile_id=c.id,
                    by_date=target,
                    entry_time=final_entry,
                    exit_time=final_exit,
                    exit_with=final_who,
                    comment=comment,
                    template_id=template_id,
                    repeat_pattern=repeat_pattern,
                )
                click.echo(f"  ✓ {c.name}")
                success_count += 1
            except Exception as e:
                click.echo(f"  ✗ {c.name}: {e}")

        click.echo()
        click.echo(f"Updated {success_count}/{len(children)} children.")


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
        print_error(f"--from-date ({from_date_d}) must be on or before --to-date ({to_date_d})")
        return

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        institution_profile_ids = [child.id for child in prof.children]

        try:
            templates = await client.get_presence_templates(
                institution_profile_ids, from_date_d, to_date_d
            )
        except Exception as e:
            print_error(f"fetching presence templates: {e}")
            return

        if output_json(ctx, [dict(t) for t in templates]):
            return

        if not templates:
            print_empty("presence templates")
            return

        print_heading("Presence templates")

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

            header = name or "Unknown"
            if institution:
                header = f"{header} ({institution})"

            if not tmpl.day_templates:
                for line in format_record_lines(
                    title=header,
                    properties=[],
                    body_lines=[],
                    body_label="Body",
                    empty_body_text="(no day templates)",
                ):
                    click.echo(line)
            else:
                for day in tmpl.day_templates:
                    body_lines: list[str] = []
                    if day.entry_time or day.exit_time:
                        times = f"{day.entry_time or '?'} -> {day.exit_time or '?'}"
                        if day.exit_with:
                            times = f"{times} (picked up by: {day.exit_with})"
                        body_lines.append(times)
                    if day.spare_time_activity:
                        sta = day.spare_time_activity
                        body_lines.append(f"Activity: {sta.start_time} - {sta.end_time}")
                        if sta.comment:
                            body_lines.append(sta.comment)
                    if day.comment:
                        body_lines.append(f"Note: {day.comment}")

                    for line in format_record_lines(
                        title=day.by_date or "Day template",
                        properties=[("Child", header)],
                        body_lines=body_lines,
                        body_label="Body",
                        empty_body_text="(no details)",
                    ):
                        click.echo(line)
                    click.echo()


@cli.command("presence")
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
    help="End date (YYYY-MM-DD). Defaults to today.",
)
@click.option(
    "--week",
    type=str,
    default=None,
    help="Show activity/week overview for the given ISO week (YYYY-Wnn).",
)
@click.option(
    "--states",
    is_flag=True,
    default=False,
    help="Show current presence states instead of registrations.",
)
@click.pass_context
@async_cmd
async def presence(ctx, from_date, to_date, week, states):
    """Fetch presence registrations, current states, or weekly activity overview."""
    tz = ZoneInfo("Europe/Copenhagen")
    now = datetime.datetime.now(tz)

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        institution_profile_ids = [child.id for child in prof.children]

        # Activity/week overview mode
        if week:
            try:
                year, w = week.split("-W")
                year_int, week_int = int(year), int(w)
            except (ValueError, AttributeError):
                print_error(f"Invalid week format '{week}'. Expected YYYY-Wnn (e.g. 2026-W10).")
                return

            try:
                overview = await client.get_activity_overview(
                    institution_profile_ids, week_int, year_int
                )
            except Exception as e:
                print_error(f"fetching activity overview: {e}")
                return

            if output_json(ctx, dict(overview) if overview else {}):
                return

            if not overview or not overview.days:
                print_empty("activity overview")
                return

            print_heading(f"Activity overview - {week}")
            for day in overview.days:
                click.echo(f"  {day.date or 'Unknown date'}")
                if not day.activities:
                    click.echo("    (no activities)")
                else:
                    for act in day.activities:
                        time_range = ""
                        if act.start_time or act.end_time:
                            time_range = f" ({act.start_time or '?'} - {act.end_time or '?'})"
                        click.echo(f"    {act.title or 'Untitled'}{time_range}")
                click.echo()
            return

        # Current states mode
        if states:
            try:
                state_list = await client.get_presence_states(institution_profile_ids)
            except Exception as e:
                print_error(f"fetching presence states: {e}")
                return

            if output_json(ctx, [dict(s) for s in state_list]):
                return

            if not state_list:
                print_empty("presence states")
                return

            print_heading("Current presence states")
            for s in state_list:
                name = s.name or f"Profile {s.institution_profile_id}"
                status_text = s.status.display_name if s.status else "Unknown"
                click.echo(f"  {name}: {status_text}")
            return

        # Default: registrations mode
        from_date_d = from_date.date() if from_date else now.date()
        to_date_d = to_date.date() if to_date else now.date()

        if from_date_d > to_date_d:
            print_error(f"--from-date ({from_date_d}) must be on or before --to-date ({to_date_d})")
            return

        try:
            registrations = await client.get_presence_registrations(
                institution_profile_ids, from_date_d, to_date_d
            )
        except Exception as e:
            print_error(f"fetching presence registrations: {e}")
            return

        if output_json(ctx, [dict(r) for r in registrations]):
            return

        if not registrations:
            print_empty("presence registrations")
            return

        print_heading("Presence registrations")
        child_map = {c.id: c.name for c in prof.children}
        for reg in registrations:
            name = child_map.get(
                reg.institution_profile_id, f"Profile {reg.institution_profile_id}"
            )
            status_text = reg.status.display_name if reg.status else "Unknown"
            props = [("Child", name), ("Status", status_text)]
            if reg.entry_time or reg.exit_time:
                props.append(("Time", f"{reg.entry_time or '?'} - {reg.exit_time or '?'}"))
            if reg.check_in_time:
                props.append(("Checked in", reg.check_in_time))
            if reg.check_out_time:
                props.append(("Checked out", reg.check_out_time))
            for line in format_record_lines(
                title=reg.date or "Unknown date",
                properties=props,
                body_lines=[],
                body_label="Body",
                empty_body_text="",
            ):
                if line.strip():
                    click.echo(line)
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

    is_json = ctx.obj.get("OUTPUT_FORMAT") == "json"
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
                click.echo(line)
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
        if not is_json:
            click.echo("Status")
            click.echo()

        overview_data = []
        for c in children:
            day_tmpl = day_template_by_child.get(c.id)

            ov = None
            if is_today:
                try:
                    ov = await client.get_daily_overview(c.id)
                except Exception as e:
                    _log.warning("Could not fetch daily overview for %s: %s", c.name, e)

            if is_json:
                entry = {"child": dict(c)}
                if ov is not None:
                    entry["overview"] = dict(ov)
                if day_tmpl:
                    entry["presence_template"] = dict(day_tmpl)
                overview_data.append(entry)
                continue

            click.echo(c.name)

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

        if json_result is not None:
            json_result["status"] = overview_data

        # ── Schedule ──────────────────────────────────────────────────────────
        try:
            events = await client.get_calendar_events(
                child_institution_profile_ids, day_start, day_end
            )
        except Exception as e:
            events = []
            _log.warning("Could not fetch calendar events: %s", e)

        if json_result is not None:
            json_result["calendar_events"] = [dict(ev) for ev in events]

        if not is_json:
            click.echo("Schedule")
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
                click.echo("No events today.")
            click.echo()

        # ── Homework due today ────────────────────────────────────────────────
        today_tasks: list = []
        widget_ctx = await _get_widget_context(client, prof)
        if widget_ctx is not None:
            child_filter, institution_filter, session_uuid = widget_ctx

            if child:
                selected_user_ids = {
                    str(c._raw["userId"]) for c in children if c._raw and "userId" in c._raw
                }
                child_filter = [uid for uid in child_filter if uid in selected_user_ids]

            from .const import WIDGET_MIN_UDDANNELSE_TASKS

            try:
                all_tasks = await client.widgets.get_mu_tasks(
                    WIDGET_MIN_UDDANNELSE_TASKS,
                    child_filter,
                    institution_filter,
                    week,
                    session_uuid,
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

        if json_result is not None:
            json_result["homework_due_today"] = [dict(t) for t in today_tasks]

        if not is_json and today_tasks:
            click.echo("Homework due today")
            click.echo()
            for task in today_tasks:
                subjects = ", ".join(cls.subject_name for cls in task.classes if cls.subject_name)
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

        if json_result is not None:
            json_result["unread_messages"] = [dict(t) for t in unread_threads]
            click.echo(to_json(json_result))
            return

        if unread_threads:
            click.echo("Unread messages")
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
                click.echo(thread.subject)
                if meta:
                    click.echo(f"  Meta: {' | '.join(meta)}")
                click.echo()
                try:
                    msgs = await client.get_messages_for_thread(thread.thread_id)
                    for msg in msgs:
                        msg_raw = msg._raw or {}
                        sender = msg_raw.get("sender", {}).get("fullName", "Unknown")
                        send_date = msg_raw.get("sendDateTime", "")
                        click.echo(f"Author: {sender}")
                        if send_date:
                            click.echo(f"Date: {send_date}")
                        for line in msg.content.splitlines():
                            if line.strip():
                                click.echo(line)
                        click.echo()
                except Exception as e:
                    _log.warning("Could not fetch messages for thread %s: %s", thread.thread_id, e)
                    click.echo()


@cli.command("agent-setup")
@click.option(
    "--global",
    "install_global",
    is_flag=True,
    default=False,
    help="Install skill globally (~/.claude/skills/) instead of in the current project.",
)
def agent_setup(install_global):
    """Install an agent skill so Claude Code / OpenCode can use the Aula CLI.

    Creates a SKILL.md file that teaches AI agents how to query Aula for
    school data.  Works with any tool that follows the Agent Skills standard
    (Claude Code, OpenCode, etc.).
    """
    from pathlib import Path

    from .agent_skill import generate_skill_md

    # ── Detect tools ────────────────────────────────────────────────────────
    home = Path.home()
    has_claude = (home / ".claude").is_dir()
    has_opencode = (home / ".config" / "opencode").is_dir()

    if install_global:
        skill_dir = home / ".claude" / "skills" / "aula" / "SKILL.md"
    else:
        skill_dir = Path.cwd() / ".claude" / "skills" / "aula" / "SKILL.md"

    skill_dir.parent.mkdir(parents=True, exist_ok=True)
    skill_dir.write_text(generate_skill_md())

    click.echo(f"Skill installed: {skill_dir}")

    agents: list[str] = []
    if has_claude:
        agents.append("Claude Code")
    if has_opencode:
        agents.append("OpenCode")
    if agents:
        click.echo(f"Detected: {', '.join(agents)}")
    else:
        click.echo("No agent tools detected, but the skill file is ready.")

    scope = "globally (all projects)" if install_global else "for this project"
    click.echo(f"Installed {scope}. Agents can now use /aula or ask about Aula data.")


if __name__ == "__main__":
    cli()
