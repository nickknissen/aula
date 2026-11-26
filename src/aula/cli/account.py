import click

from ..models import (
    Profile,
)
from ..token_storage import FileTokenStorage
from ..utils.output import (
    echo,
    format_row,
    output_json,
    print_empty,
    print_error,
    print_heading,
)
from ._app import _get_client, _log_in, _token_file, async_cmd, cli


@cli.command()
@click.pass_context
@async_cmd
async def logout(ctx):
    """Forget the cached session, so the next command logs in through MitID again"""
    token_file = _token_file(ctx)
    removed = await FileTokenStorage(token_file).clear()
    if output_json(ctx, {"status": "ok", "removed": removed, "path": str(token_file)}):
        return
    if removed:
        echo(f"Logged out. Removed {token_file}")
    else:
        echo(f"No stored session at {token_file}")


@cli.command()
@click.option("--force", is_flag=True, help="Log in through MitID even if the saved session works.")
@click.pass_context
@async_cmd
async def login(ctx, force: bool):
    """Authenticate and initialize session"""
    client, identity = await _log_in(ctx, force_login=force)
    async with client:
        result: dict[str, str | int] = {"status": "ok", "api_url": client.api_url}
        if identity:
            result["identity"] = identity
        if output_json(ctx, result):
            return
        as_identity = f" as MitID identity {identity}" if identity else ""
        echo(f"Logged in{as_identity}. API URL: {client.api_url}")


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
        echo(format_row(prof.display_name, f"ID {prof.profile_id}"))

        if prof.institution_profile_ids:
            ids = ", ".join(str(i) for i in prof.institution_profile_ids)
            echo(format_row("Institution profile IDs", ids))

        if prof.children:
            echo(f"Children ({len(prof.children)}):")
            for child in prof.children:
                echo(f"- {format_row(child.name, f'ID {child.id}', f'Profile {child.profile_id}')}")
                if child.institution_name:
                    echo(f"  Institution: {child.institution_name}")
        else:
            print_empty("children")


@cli.command("profile-details")
@click.option(
    "--institution-profile-id",
    type=int,
    default=None,
    help="Institution profile ID to fetch details for.",
)
@click.pass_context
@async_cmd
async def profile_details(ctx, institution_profile_id):
    """Show extended profile details (email, phone, address)."""
    async with await _get_client(ctx) as client:
        if not institution_profile_id:
            try:
                prof = await client.get_profile()
                if prof.institution_profile_ids:
                    institution_profile_id = prof.institution_profile_ids[0]
                else:
                    print_error("no institution profile IDs found")
                    return
            except Exception as e:
                print_error(f"fetching profile: {e}")
                return

        try:
            master_data = await client.get_profile_master_data(institution_profile_id)
        except Exception as e:
            print_error(f"fetching profile details: {e}")
            return

        if master_data is None:
            print_empty("profile details")
            return

        if output_json(ctx, dict(master_data)):
            return

        print_heading("Profile Details")
        if master_data.first_name or master_data.last_name:
            echo(format_row("Name", f"{master_data.first_name} {master_data.last_name}"))
        if master_data.email:
            echo(format_row("Email", master_data.email))
        if master_data.phone_number:
            echo(format_row("Phone", master_data.phone_number))
        if master_data.mobile_phone:
            echo(format_row("Mobile", master_data.mobile_phone))
        if master_data.address:
            addr_parts = [master_data.address]
            if master_data.postal_code or master_data.city:
                addr_parts.append(f"{master_data.postal_code} {master_data.city}".strip())
            echo(format_row("Address", ", ".join(addr_parts)))
        if master_data.municipality:
            echo(format_row("Municipality", master_data.municipality))
        if master_data.portal_role:
            echo(format_row("Role", master_data.portal_role))


@cli.command("consents")
@click.pass_context
@async_cmd
async def consents(ctx):
    """Show consent responses."""
    async with await _get_client(ctx) as client:
        try:
            prof = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        try:
            result = await client.get_consent_responses(prof.institution_profile_ids)
        except Exception as e:
            print_error(f"fetching consents: {e}")
            return

        if output_json(ctx, [dict(c) for c in result]):
            return

        if not result:
            print_empty("consent responses")
            return

        print_heading("Consent Responses")
        for c in result:
            status_str = f" [{c.status}]" if c.status else ""
            echo(format_row(c.title, f"ID {c.consent_id}{status_str}"))
            if c.description:
                echo(f"  {c.description}")
            if c.responded_at:
                echo(f"  Responded: {c.responded_at}")
            if c.institution_code:
                echo(f"  Institution: {c.institution_code}")


@cli.command("notification-settings")
@click.pass_context
@async_cmd
async def notification_settings(ctx):
    """Show notification settings for the active profile."""
    async with await _get_client(ctx) as client:
        try:
            result = await client.get_notification_settings()
        except Exception as e:
            print_error(f"fetching notification settings: {e}")
            return

        if output_json(ctx, [dict(s) for s in result]):
            return

        if not result:
            print_empty("notification settings")
            return

        print_heading("Notification Settings")
        for s in result:
            status_parts = []
            if s.push_enabled:
                status_parts.append("push")
            if s.email_enabled:
                status_parts.append("email")
            enabled = "Yes" if s.is_enabled else "No"
            channels = f" ({', '.join(status_parts)})" if status_parts else ""
            echo(format_row(s.module, f"Enabled: {enabled}{channels}"))
