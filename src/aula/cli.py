#!/usr/bin/env python3
import asyncio
import functools
import json
import sys
from dataclasses import asdict

import click

# On Windows, use SelectorEventLoopPolicy to avoid 'Event loop closed' issues
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from .api_client import AulaApiClient, Profile, DailyOverview


# Decorator to run async functions within Click commands
def async_cmd(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


# Define the main group
@click.group()
@click.option("--username", required=True, help="Aula username")
@click.option("--password", required=True, help="Aula password")
@click.pass_context
def cli(ctx, username, password):
    """CLI for testing AulaApiClient"""
    # Store username and password in the context
    ctx.ensure_object(dict)
    ctx.obj["USERNAME"] = username
    ctx.obj["PASSWORD"] = password


async def _get_client(ctx):
    client = AulaApiClient(ctx.obj["USERNAME"], ctx.obj["PASSWORD"])
    # Ensure login for commands that require auth (except login itself)
    # We get the command name from the context
    command_name = ctx.invoked_subcommand
    if command_name != "login":
        if not await client.is_logged_in():
            await client.login()
    return client


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
                f"{child_prefix} Child {i + 1}: {child.name} (ID: {child.profile_id})"
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
    client: AulaApiClient = await _get_client(ctx)
    child_ids = []

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
