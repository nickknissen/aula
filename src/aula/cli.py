#!/usr/bin/env python3
import asyncio
import datetime
import functools
import logging
import os
import sys
from zoneinfo import ZoneInfo

import click
from dotenv import load_dotenv

# On Windows, use SelectorEventLoopPolicy to avoid 'Event loop closed' issues
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from .api_client import AulaApiClient
from .config import CONFIG_FILE, DEFAULT_TOKEN_FILE, load_config, save_config
from .models import DailyOverview, Message, MessageThread, Profile
from .token_storage import FileTokenStorage

# Load environment variables from .env file
load_dotenv()


# Decorator to run async functions within Click commands
def async_cmd(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


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


async def _get_client(ctx: click.Context) -> AulaApiClient:
    """Create an authenticated AulaApiClient."""
    username = get_mitid_username(ctx)
    token_storage = FileTokenStorage(DEFAULT_TOKEN_FILE)
    client = AulaApiClient(
        mitid_username=username,
        token_storage=token_storage,
    )
    await client.login()
    return client


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

        click.echo(f"User: {prof.display_name} (ID: {prof.profile_id})")

        # Print main profile attributes
        for k, v in prof:
            click.echo(f"  {k}: {v}")

        # Print children if they exist
        if prof.children:
            click.echo("  Children:")
            for i, child in enumerate(prof.children):
                child_prefix = "    " if i == len(prof.children) - 1 else "    "
                click.echo(
                    f"{child_prefix}Child {i + 1}: {child.name} (profile ID: {child.profile_id})"
                )

                child_indent = "        "
                fields = list(child)
                for j, (k, v) in enumerate(fields):
                    click.echo(f"{child_indent}{k}: {v}")
                click.echo()
        else:
            click.echo("  No children associated with this profile.")


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
@click.pass_context
@async_cmd
async def messages(ctx, limit):
    """Fetch the latest message threads and their messages."""
    async with await _get_client(ctx) as client:
        click.echo(f"Fetching the latest {limit} message threads...\n")

        try:
            threads: list[MessageThread] = await client.get_message_threads()
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


if __name__ == "__main__":
    cli()
