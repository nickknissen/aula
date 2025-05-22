#!/usr/bin/env python3
import asyncio
import functools
import os
import sys
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
import datetime

import click
import pytz
from dotenv import load_dotenv

# On Windows, use SelectorEventLoopPolicy to avoid 'Event loop closed' issues
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from .api_client import AulaApiClient, DailyOverview, Profile
from .models import Message, MessageThread

# Load environment variables from .env file
load_dotenv()

# Configuration file path
CONFIG_DIR = Path.home() / ".config" / "aula"
CONFIG_FILE = CONFIG_DIR / "config.json"


def ensure_config_dir() -> None:
    """Ensure the configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    """Load configuration from file."""
    ensure_config_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to file."""
    ensure_config_dir()
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except IOError as e:
        click.echo(f"Error saving configuration: {e}", err=True)


# Decorator to run async functions within Click commands
def async_cmd(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def prompt_for_credentials() -> tuple[str, str]:
    """Prompt user for username and password."""
    click.echo("Aula authentication required")
    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)
    return username, password


def get_credentials(ctx: click.Context) -> tuple[str, str]:
    """Get credentials from context, environment, or prompt."""
    # First try to get from context (command line)
    username = ctx.obj.get("USERNAME")
    password = ctx.obj.get("PASSWORD")

    # Then try environment variables
    if not username:
        username = os.getenv("AULA_USERNAME")
    if not password:
        password = os.getenv("AULA_PASSWORD")

    # Then try config file
    if not username or not password:
        config = load_config()
        if not username and "username" in config:
            username = config["username"]
        if not password and "password" in config:
            password = config["password"]

    # Finally, prompt if still missing
    if not username or not password:
        username, password = prompt_for_credentials()

        # Ask to save to config
        if click.confirm(
            "Would you like to save these credentials to your config file?"
        ):
            config = load_config()
            config.update({"username": username, "password": password})
            save_config(config)
            click.echo(f"Credentials saved to {CONFIG_FILE}")

    return username, password


# Define the main group
@click.group()
@click.option(
    "--username",
    help="Aula username (can also be set via AULA_USERNAME env var or config file)",
)
@click.option(
    "--password",
    help="Aula password (can also be set via AULA_PASSWORD env var or config file)",
)
@click.pass_context
def cli(ctx, username: Optional[str], password: Optional[str]):
    """CLI for interacting with Aula API"""
    # Initialize context
    ctx.ensure_object(dict)

    # Store provided credentials in context
    if username:
        ctx.obj["USERNAME"] = username
    if password:
        ctx.obj["PASSWORD"] = password

    # Get credentials (will prompt if needed)
    try:
        username, password = get_credentials(ctx)
        ctx.obj["USERNAME"] = username
        ctx.obj["PASSWORD"] = password
    except Exception as e:
        click.echo(f"Error getting credentials: {e}", err=True)
        ctx.exit(1)


async def _get_client(ctx):
    try:
        username, password = get_credentials(ctx)
        client = AulaApiClient(username, password)
        # Ensure login for commands that require auth (except login itself)
        command_name = ctx.invoked_subcommand
        if command_name != "login":
            if not await client.is_logged_in():
                await client.login()
        return client
    except Exception as e:
        click.echo(f"Error initializing client: {e}", err=True)
        ctx.exit(1)


# Define commands
@cli.command()
@click.pass_context
@async_cmd
async def login(ctx):
    """Authenticate and initialize session"""
    client = AulaApiClient(ctx.obj["USERNAME"], ctx.obj["PASSWORD"])
    await client.login()
    click.echo(f"Logged in. API URL: {client.api_url}")


@cli.command()
@click.pass_context
@async_cmd
async def profile(ctx):
    """Fetch profile list and display structured info."""
    client = await _get_client(ctx)
    try:
        profile: Profile = await client.get_profile()
    except ValueError as e:
        click.echo(f"Error fetching or parsing profile data: {e}")
        return
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}")
        return

    click.echo(f"User: {profile.display_name} (ID: {profile.profile_id})")
    click.echo(f"├── Institution Profile IDs: {profile.institution_profile_ids}")

    # Print main profile attributes
    for k, v in profile:
        click.echo(f"├── {k}: {v}")

    # Print children if they exist
    if profile.children:
        click.echo("└── Children:")
        for i, child in enumerate(profile.children):
            child_prefix = "    └──" if i == len(profile.children) - 1 else "    ├──"
            click.echo(
                f"{child_prefix} Child {i + 1}: {child.name} (profile ID: {child.profile_id})"
            )

            # Print child attributes
            child_indent = "        "
            fields = list(child)  # Convert iterator to list to check last item
            for j, (k, v) in enumerate(fields):
                attr_prefix = "└──" if j == len(fields) - 1 else "├──"
                click.echo(f"{child_indent}{attr_prefix} {k}: {v}")
            click.echo()  # Add a newline between children

    else:
        click.echo("└── No children associated with this profile.")


@cli.command()
@click.option("--child-id", type=int, help="Specify a single child ID.")
@click.pass_context
@async_cmd
async def overview(ctx, child_id):
    """Fetch the daily overview for a child or all children."""
    click.echo("Fetching overview...")
    client: AulaApiClient = await _get_client(ctx)
    child_ids = []
    click.echo("Client ready...")

    if child_id:
        child_ids.append(child_id)
        click.echo(f"Fetching overview for child ID: {child_id}")
    else:
        click.echo("Fetching overview for all children...")
        try:
            profile: Profile = await client.get_profile()
            if not profile.children:
                click.echo("No children found in profile.")
                return
            child_ids = [child.id for child in profile.children]
        except Exception as e:
            click.echo(f"Error fetching profile to get children IDs: {e}")
            return

    for c_id in child_ids:
        try:
            overview_data: DailyOverview = await client.get_daily_overview(c_id)
            click.echo(f"\n--- Overview for Child ID: {c_id} ---")

            for k, v in overview_data:
                click.echo(f"{k}: {v}")

        except Exception as e:
            click.echo(f"Error fetching overview for child ID {c_id}: {e}")


@cli.command()
@click.option("--limit", type=int, default=5, help="Number of threads to fetch.")
@click.pass_context
@async_cmd
async def messages(ctx, limit):
    """Fetch the latest message threads and their messages."""
    client: AulaApiClient = await _get_client(ctx)
    click.echo(f"Fetching the latest {limit} message threads...")

    try:
        threads: List[MessageThread] = await client.get_message_threads()
        threads = threads[:limit]  # Apply limit if necessary
    except Exception as e:
        click.echo(f"Error fetching message threads: {e}")
        return

    if not threads:
        click.echo("No message threads found.")
        return

    for i, thread in enumerate(threads):
        click.echo(f"\n--- Thread {i + 1}/{len(threads)} (ID: {thread.thread_id}) ---")
        # Print thread details (you might want to add more from MessageThread model)
        click.echo(f"Subject: {thread.subject}")
        # Access data from the _raw dictionary
        last_updated_str = (
            thread._raw.get("lastUpdatedDate", "N/A") if thread._raw else "N/A"
        )
        participants_list = thread._raw.get("participants", []) if thread._raw else []
        click.echo(f"Last Updated: {last_updated_str}")
        click.echo(
            f"Participants: {', '.join(p.get('name', 'N/A') for p in participants_list)}"
        )

        click.echo("  Fetching latest messages...")
        try:
            messages_list: List[Message] = await client.get_messages_for_thread(
                thread.thread_id
            )
            if not messages_list:
                click.echo("  No messages found in this thread.")
            else:
                click.echo(f"  Latest {len(messages_list)} Messages:")
                for j, msg in enumerate(messages_list):
                    click.echo(
                        f"    {j + 1}. ID: {msg.id}\n       Content: {msg.content}"
                    )

        except Exception as e:
            click.echo(f"  Error fetching messages for thread {thread.thread_id}: {e}")


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
    default=datetime.datetime.now(pytz.timezone("CET")),
    help="Start date for events (YYYY-MM-DD). Defaults to today.",
)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=(datetime.datetime.now(pytz.timezone("CET")) + datetime.timedelta(days=7)),
    help="End date for events (YYYY-MM-DD). Defaults to 7 days from today.",
)
@click.pass_context
@async_cmd
async def calendar(ctx, institution_profile_id, start_date, end_date):
    """Fetch calendar events for children."""
    client: AulaApiClient = await _get_client(ctx)
    click.echo("Fetching calendar events...")

    institution_profile_ids = list(institution_profile_id)

    # If no specific child IDs provided, get all associated children
    if not institution_profile_ids:
        try:
            profile = await client.get_profile()
            child_ids = [c.id for c in profile.children]

            institution_profile_ids = child_ids

            if not institution_profile_ids:
                click.echo(
                    "No children or institution IDs found associated with this profile."
                )
                return

            click.echo(
                f"Fetching for institution IDs: {', '.join(map(str, institution_profile_ids))}"
            )
        except Exception as e:
            click.echo(f"Error fetching profile to get child IDs: {e}")
            return
    else:
        click.echo(
            f"Fetching for children: {', '.join(map(str, institution_profile_ids))}"
        )

    try:
        events = await client.get_calendar_events(
            institution_profile_ids, start_date, end_date
        )

        if not events:
            click.echo("No calendar events found for the specified criteria.")
            return

        click.echo("\n--- Calendar Events ---")
        for event in events:
            click.echo(f"ID: {event.id}")
            click.echo(f"Title: {event.title}")
            click.echo(f"Location: {event.location}")
            click.echo(f"Belongs to: {event.belongs_to}")
            # If start date and end date is the same show it on the same line
            if event.start_datetime.date() == event.end_datetime.date():
                click.echo(
                    f"Date: {event.start_datetime.date()} {event.start_datetime.time()} - {event.end_datetime.time()}"
                )
            else:
                click.echo(f"Start: {event.start_datetime}")
                click.echo(f"End: {event.end_datetime}")
            if event.has_substitute:
                click.echo(f"Substitute: {event.substitute_name}")
            else:
                click.echo(f"Teacher: {event.teacher_name}")
            # Optionally display more details from event._raw if needed
            # click.echo(f"Raw: {event._raw}")
            click.echo("--")

    except Exception as e:
        click.echo(f"Error fetching calendar events: {e}")
        raise


if __name__ == "__main__":
    cli()
