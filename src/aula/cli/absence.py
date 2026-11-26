import click

from ..api_client import VACATION_COMMENT_MAX_LENGTH, AulaApiClient, validate_vacation
from ..http import HttpRequestError
from ..models import (
    Child,
    DailyOverview,
    PresenceModule,
    PresenceModulePermission,
    PresenceState,
    Profile,
)
from ..utils.dates import aula_today
from ..utils.diagnostics import credential_logger
from ..utils.output import (
    echo,
    output_json,
    print_empty,
    print_error,
    print_heading,
)
from ._app import _get_client, async_cmd, cli

_LOGGER = credential_logger(__name__)


@cli.command("report-sick")
@click.option(
    "--child",
    "child_ids",
    type=int,
    multiple=True,
    help="Specific child institution profile ID(s). Omit to report all children.",
)
@click.option(
    "--undo",
    is_flag=True,
    default=False,
    help="Take the sick report back (sets the child to 'Ikke kommet').",
)
@click.option(
    "--present",
    is_flag=True,
    default=False,
    help="With --undo, set 'Til stede' instead, for a child who is at school.",
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
async def report_sick(ctx, child_ids, undo, present, yes):
    """Report a child sick for today, or take the report back.

    Writes to Aula and notifies the institution. Applies to today only; Aula has
    no future-dated sick report, so use `register-absence` or `update-presence`
    for a planned absence.

    An institution can withhold this from guardians. When it has, the child is
    skipped with a note rather than sent to a call Aula would reject.

    Examples:

      aula report-sick

      aula report-sick --child 123456 -y

      aula report-sick --undo --child 123456 -y
    """
    if present and not undo:
        print_error("--present only applies together with --undo")
        return

    if undo:
        new_status = PresenceState.PRESENT if present else PresenceState.NOT_PRESENT
    else:
        new_status = PresenceState.SICK

    is_json = bool(ctx.obj) and ctx.obj.get("OUTPUT_FORMAT") == "json"
    if is_json and not yes:
        print_error("--output json requires --yes, since this command writes to Aula")
        return

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if not prof.children:
            print_empty("children")
            return

        if child_ids:
            children = [c for c in prof.children if c.id in child_ids]
            if not children:
                print_error(f"no children found with IDs: {list(child_ids)}")
                return
        else:
            children = prof.children

        # Aula rejects the write when the institution has not granted guardians
        # the report_sick module, so check first and say which child and why.
        # A configuration we cannot read is not treated as a denial.
        blocked: dict[int, str] = {}
        try:
            configs = await client.get_presence_configuration([c.id for c in children])
        except HttpRequestError as e:
            _LOGGER.warning("Could not fetch presence configuration: %s", e)
            configs = []

        by_child = {c.child_id: c for c in configs if c.child_id is not None}
        for c in children:
            config = by_child.get(c.id)
            if config is None:
                continue
            if not config.can_edit(PresenceModule.REPORT_SICK):
                permission = config.permission(PresenceModule.REPORT_SICK)
                blocked[c.id] = (
                    "sick reporting is read-only for guardians"
                    if permission is PresenceModulePermission.READABLE
                    else "the institution has not enabled sick reporting for guardians"
                )

        targets = [c for c in children if c.id not in blocked]

        # Current status, so the confirmation shows what actually changes.
        current: dict[int, DailyOverview] = {}
        for c in targets:
            try:
                overview = await client.get_daily_overview(c.id)
                if overview:
                    current[c.id] = overview
            except HttpRequestError as e:
                _LOGGER.warning("Could not fetch daily overview for %s: %s", c.name, e)

        if not is_json:
            print_heading("Report sick" if not undo else "Take sick report back")
            echo()
            for c in targets:
                overview = current.get(c.id)
                was = overview.status.danish_name if overview and overview.status else "?"
                echo(f"  {c.name:<30s}  {was:<18s} -> {new_status.danish_name}")
            for child_id, reason in blocked.items():
                name = next((c.name for c in children if c.id == child_id), str(child_id))
                echo(f"  {name:<30s}  skipped: {reason}")
            echo()

        if not targets:
            print_empty("children this can be applied to")
            return

        if not yes and not click.confirm("Apply to Aula now?"):
            echo("Cancelled.")
            return

        target_ids = [c.id for c in targets]
        try:
            await client.update_presence_status(target_ids, new_status)
        except HttpRequestError as e:
            print_error(f"updating presence status: {e}")
            return

        result = {
            "status": new_status.name,
            "status_value": new_status.value,
            "updated": [{"id": c.id, "name": c.name} for c in targets],
            "skipped": [
                {
                    "id": child_id,
                    "name": next((c.name for c in children if c.id == child_id), None),
                    "reason": reason,
                }
                for child_id, reason in blocked.items()
            ],
        }
        if output_json(ctx, result):
            return

        for c in targets:
            echo(f"  ✓ {c.name}")
        echo()
        echo(f"Set {len(targets)} child(ren) to {new_status.display_name}.")


async def _vacation_denials(client: AulaApiClient, children: list[Child]) -> dict[int, str]:
    """Map each child Aula is known to refuse an absence for to the reason.

    A child Aula has not said either way about is left out, so Aula decides.
    """
    denials = {
        c.id: "you have no custody of or extended access to this child; "
        "a guardian with custody must register it"
        for c in children
        if c.has_custody_or_extended_access is False
    }
    candidates = [c for c in children if c.id not in denials]
    if not candidates:
        return denials

    try:
        configs = await client.get_presence_configuration([c.id for c in candidates])
    except HttpRequestError as e:
        _LOGGER.warning("Could not fetch presence configuration, leaving it to Aula: %s", e)
        return denials

    by_child = {c.child_id: c for c in configs if c.child_id is not None}
    for child in candidates:
        config = by_child.get(child.id)
        if config is None:
            _LOGGER.warning("No presence configuration for child %s, leaving it to Aula", child.id)
        elif not config.can_edit(PresenceModule.VACATION):
            denials[child.id] = (
                "absence registration is read-only for guardians; contact the institution"
                if config.permission(PresenceModule.VACATION) is PresenceModulePermission.READABLE
                else "the institution has not enabled absence registration for guardians; "
                "contact the institution"
            )
    return denials


@cli.command("register-absence")
@click.option(
    "--child",
    "child_ids",
    type=int,
    multiple=True,
    help="Child institution profile ID; repeat for several. Omit to register all children.",
)
@click.option(
    "--from",
    "start_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    help="First day of the absence (YYYY-MM-DD), today or later.",
)
@click.option(
    "--to",
    "end_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    help="End date (YYYY-MM-DD), at most a year after --from. Use the --from date for one day.",
)
@click.option(
    "--comment",
    default="",
    help=f"Note to the institution, at most {VACATION_COMMENT_MAX_LENGTH} characters.",
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
async def register_absence(ctx, child_ids, start_date, end_date, comment, yes):
    """Register a planned absence (ferie/fri) for children.

    Writes to Aula. For illness today use `report-sick` instead; `vacations`
    lists the institution's vacation requests, which are a separate thing.

    A child is skipped with the reason when Aula says you may not register an
    absence for them. When Aula does not say, because the presence configuration
    cannot be read or has no entry for the child, the absence is sent and Aula
    decides; run with -v to see when that happens.

    Exits non-zero when nothing was registered, unless you cancelled.

    Examples:

      aula register-absence --from 2026-12-21 --to 2026-12-23

      aula register-absence --child 123456 --from 2026-11-16 --to 2026-11-16 -y

      aula register-absence --from 2026-11-16 --to 2026-11-20 --comment Ferie
    """
    is_json = bool(ctx.obj) and ctx.obj.get("OUTPUT_FORMAT") == "json"
    if is_json and not yes:
        print_error("--output json requires --yes, since this command writes to Aula", err=True)
        ctx.exit(1)

    start, end = start_date.date(), end_date.date()
    try:
        validate_vacation(start, end, comment, today=aula_today())
    except ValueError as e:
        print_error(str(e), err=is_json)
        ctx.exit(1)

    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}", err=is_json)
            ctx.exit(1)

        children = prof.children
        if child_ids:
            unknown = sorted(set(child_ids) - {c.id for c in children})
            if unknown:
                print_error(f"no children found with IDs: {unknown}", err=is_json)
                ctx.exit(1)
            children = [c for c in children if c.id in child_ids]
        if not children:
            print_error("no children on this profile to register an absence for", err=is_json)
            ctx.exit(1)

        denials = await _vacation_denials(client, children)
        targets = [c for c in children if c.id not in denials]
        result = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "comment": comment,
            "registered": [{"id": c.id, "name": c.name} for c in targets],
            "skipped": [
                {"id": c.id, "name": c.name, "reason": denials[c.id]}
                for c in children
                if c.id in denials
            ],
        }

        if not is_json:
            print_heading("Register absence")
            echo()
            echo(f"  From:     {start.isoformat()}")
            echo(f"  To:       {end.isoformat()}")
            echo(f"  Comment:  {comment or '(none)'}")
            echo()
            for c in children:
                note = f"skipped: {denials[c.id]}" if c.id in denials else ""
                echo(f"  {c.name:<30s}  {note}".rstrip())
            echo()

        if not targets:
            if not output_json(ctx, result):
                print_empty("children this can be applied to")
            ctx.exit(1)

        if not yes and not click.confirm("Register this absence in Aula now?"):
            echo("Cancelled.")
            return

        try:
            await client.add_vacation([c.id for c in targets], start, end, comment)
        except (HttpRequestError, ValueError) as e:
            print_error(f"registering absence: {e}", err=is_json)
            ctx.exit(1)

    if output_json(ctx, result):
        return
    for c in targets:
        echo(f"  ✓ {c.name}")
    echo()
    echo(f"Registered an absence from {start} to {end} for {len(targets)} child(ren).")
