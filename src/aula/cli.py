#!/usr/bin/env python3
"""CLI for interacting with Aula API and data providers."""

import asyncio
import datetime
import functools
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional, TypeVar

import click
import pytz
from dotenv import load_dotenv

from .api_client import AulaApiClient, DailyOverview, Profile
from .cli_provider import register_provider_commands
from .models import Message, MessageThread

# Type variable for async functions
T = TypeVar("T")

# On Windows, use SelectorEventLoopPolicy to avoid 'Event loop closed' issues
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load environment variables from .env file
load_dotenv()

# Configuration file path
CONFIG_DIR = Path.home() / ".config" / "aula"
CONFIG_FILE = CONFIG_DIR / "config.json"


def ensure_config_dir() -> None:
    """Ensure the configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    """Load configuration from file."""
    ensure_config_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file."""
    ensure_config_dir()
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except OSError as e:
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
    """Get credentials from context, environment, or prompt.
    
    Args:
        ctx: Click context object
        
    Returns:
        Tuple of (username, password)
        
    Raises:
        click.UsageError: If credentials cannot be obtained
    """
    username = None
    password = None
    
    # Try to get from command line context first
    if ctx.obj:
        username = ctx.obj.get("USERNAME")
        password = ctx.obj.get("PASSWORD")

    
    # Try environment variables if not found in context
    if not username:
        username = os.getenv("AULA_USERNAME")
    if not password:
        password = os.getenv("AULA_PASSWORD")
    
    # Try config file if still missing
    if not username or not password:
        try:
            config = load_config()
            if not username and "username" in config:
                username = config["username"]
            if not password and "password" in config:
                password = config["password"]
        except Exception as e:
            logger.debug(f"Failed to load config: {e}")
    
    # If we're in a non-interactive context (e.g., script), fail fast
    if not sys.stdin.isatty() and (not username or not password):
        raise click.UsageError(
            "Credentials not provided. Use -u/--username and -p/--password flags "
            "or set AULA_USERNAME and AULA_PASSWORD environment variables."
        )
    
    # Interactive prompt if still missing
    if not username or not password:
        click.echo("Aula authentication required")
        username = username or click.prompt("Username")
        password = password or click.prompt("Password", hide_input=True)
        
        # Offer to save credentials if we had to prompt
        if click.confirm("Would you like to save these credentials to your config file?"):
            try:
                config = load_config()
                config.update({"username": username, "password": password})
                save_config(config)
                click.echo(f"Credentials saved to {CONFIG_FILE}")
            except Exception as e:
                logger.warning(f"Failed to save credentials: {e}")
    
    # Final validation
    if not username or not password:
        raise click.UsageError("Username and password are required")
        
    return username, password


# Define the main group
@click.group()
@click.option("--username", "-u", help="Aula username (email)", envvar="AULA_USERNAME")
@click.option("--password", "-p", help="Aula password", envvar="AULA_PASSWORD")
@click.option("--verbose", "-v", count=True, help="Increase verbosity")
@click.option("--debug/--no-debug", default=False, help="Enable debug mode")
@click.pass_context
def cli(
    ctx: click.Context, username: Optional[str], password: Optional[str], verbose: int, debug: bool
) -> None:
    """CLI for interacting with Aula API and data providers.

    This CLI provides commands to interact with Aula and its data providers.
    """
    # Set up logging
    log_level = logging.WARNING
    if verbose == 1:
        log_level = logging.INFO
    elif verbose >= 2:
        log_level = logging.DEBUG
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True
    )
    
    # Initialize context object if it doesn't exist
    if ctx.obj is None:
        ctx.obj = {}
    
    # Store credentials in context if provided (use lowercase keys for consistency)
    if username is not None:
        ctx.obj["username"] = username
    if password is not None:
        ctx.obj["password"] = password

    # Set up debug mode if verbose is 3 or higher
    if verbose >= 3:
        import http.client as http_client

        http_client.HTTPConnection.debuglevel = 1

        # Enable asyncio debug if in debug mode
        if debug:
            logging.basicConfig(level=logging.DEBUG)
            logging.getLogger("asyncio").setLevel(logging.DEBUG)

            # Enable more verbose logging for aiohttp if needed
            logging.getLogger("aiohttp").setLevel(logging.DEBUG)
            logging.getLogger("aiohttp.client").setLevel(logging.DEBUG)

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
        
        # Store the client in the context for reuse
        ctx.obj["client"] = client
        
        # Ensure login for commands that require auth (except login itself)
        command_name = ctx.invoked_subcommand
        if command_name != "login":
            if not await client.is_logged_in():
                await client.login()
        return client
    except Exception as e:
        click.echo(f"Error initializing client: {e}", err=True)
        ctx.exit(1)


# Set up logger
logger = logging.getLogger(__name__)

# Import providers to ensure they register with ProviderRegistry
try:
    from aula.plugins.providers import biblioteket, minuddannelse
    logger.debug(f"Imported providers: {biblioteket.__name__}, {minuddannelse.__name__}")
    
    # Debug: List registered providers
    from aula.plugins.base import ProviderRegistry
    providers = ProviderRegistry.get_providers()
    logger.debug(f"Registered providers: {list(providers.keys())}")
except ImportError as e:
    logger.warning(f"Failed to import providers: {e}")

# Register provider commands with the main CLI
register_provider_commands(cli)

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
        threads: list[MessageThread] = await client.get_message_threads()
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
        last_updated_str = thread._raw.get("lastUpdatedDate", "N/A") if thread._raw else "N/A"
        participants_list = thread._raw.get("participants", []) if thread._raw else []
        click.echo(f"Last Updated: {last_updated_str}")
        click.echo(f"Participants: {', '.join(p.get('name', 'N/A') for p in participants_list)}")

        click.echo("  Fetching latest messages...")
        try:
            messages_list: list[Message] = await client.get_messages_for_thread(thread.thread_id)
            if not messages_list:
                click.echo("  No messages found in this thread.")
            else:
                click.echo(f"  Latest {len(messages_list)} Messages:")
                for j, msg in enumerate(messages_list):
                    click.echo(f"    {j + 1}. ID: {msg.id}\n       Content: {msg.content}")

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

            institution_profile_ids = profile.institution_profile_ids

        except Exception as e:
            click.echo(f"Error fetching profile to get child IDs: {e}")
            return

    click.echo(f"Fetching for institution IDs: {', '.join(map(str, institution_profile_ids))}")

    try:
        events = await client.get_calendar_events(institution_profile_ids, start_date, end_date)

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
    client: AulaApiClient = await _get_client(ctx)
    click.echo("Fetching posts...")

    institution_profile_ids = list(institution_profile_id)

    # If no specific profile IDs provided, use all from the profile
    if not institution_profile_ids:
        try:
            profile = await client.get_profile()
            institution_profile_ids = profile.institution_profile_ids
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

    click.echo(
        f"Fetching posts for institution IDs: {', '.join(map(str, institution_profile_ids))}"
    )

    try:
        posts_list = await client.get_posts(
            page=page,
            limit=limit,
            institution_profile_ids=institution_profile_ids,
        )

        if not posts_list:
            click.echo("No posts found.")
            return

        click.echo(f"\n--- Posts (Page {page}, {len(posts_list)} of {limit} per page) ---")
        for i, post in enumerate(posts_list):
            click.echo(f"\n### Post {i} ###")
            click.echo(f"Title: {post.title}")
            click.echo(f"Date: {post.timestamp}")
            click.echo(f"Author: {post.owner.full_name}")
            click.echo(f"Content: {post.content}")

            if post.attachments:
                click.echo(f"Attachments: {len(post.attachments)}")

    except Exception as e:
        click.echo(f"Error fetching posts: {e}", err=True)
        raise


if __name__ == "__main__":
    cli()
