import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import click

from ..api_client import AulaApiClient
from ..models import (
    ActivityType,
    Child,
    ChildPickupResponsibles,
    DailyOverview,
    DayTemplate,
    Profile,
)
from ..utils.diagnostics import credential_logger
from ..utils.json import to_json
from ..utils.output import (
    echo,
    format_record_lines,
    format_row,
    output_json,
    print_empty,
    print_error,
    print_heading,
)
from ._app import _get_client, async_cmd, cli

_LOGGER = credential_logger(__name__)


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
                    echo("No children found in profile.")
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
            echo(to_json(results))
            return

        for i, c_id in enumerate(child_ids):
            try:
                data: DailyOverview | None = await client.get_daily_overview(c_id)
                if data is None:
                    echo(f"- {child_names.get(c_id, f'Child {c_id}')}: unavailable")
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

                echo(format_row(display_name, status))
                if institution or group:
                    echo(f"  {' / '.join(filter(None, [institution, group]))}")

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
                if data.location and data.location.name:
                    details.append(("Location", data.location.name))
                if data.comment:
                    details.append(("Comment", data.comment))

                if details:
                    for label, value in details:
                        echo(f"  {label}: {value}")
                else:
                    echo("  No additional details.")

                if i < len(child_ids) - 1:
                    echo()

            except Exception as e:
                print_error(f"fetching overview for child {c_id}: {e}")


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
            echo("    Invalid format. Use HH:mm (e.g., 08:00, 15:30)")


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


def _prompt_pickup(names: list[str]) -> tuple[str | None, bool]:
    """Ask who picks up. Returns (chosen name or None to keep the current one, ok)."""
    echo("  Pickup responsibles:")
    for i, name in enumerate(names, 1):
        echo(f"    {i}. {name}")
    echo("    0. (keep current)")
    echo()
    choice = click.prompt("  Pick a person", type=int, default=0)
    if choice <= 0:
        return None, True
    if choice <= len(names):
        return names[choice - 1], True
    print_error(f"invalid choice {choice} (1-{len(names)})")
    return None, False


@dataclass
class PresenceNow:
    """What Aula has for the children before update-presence changes anything."""

    overviews: dict[int, DailyOverview]
    #: The planned day per child, for the target date.
    templates: dict[int, DayTemplate]
    #: Pickup people as "Name (relation)", across all children, without repeats.
    pickup_names: list[str]


@dataclass
class CurrentPlan:
    entry_time: str | None
    exit_time: str | None
    exit_with: str | None
    template_id: int | None
    comment: str | None = None
    activity_type: ActivityType = ActivityType.PICKED_UP_BY
    #: The latest time a child who goes home alone may leave.
    self_decider_end_time: str | None = None

    def activity_for(self, *, new_pickup_person: bool) -> ActivityType:
        """How the child goes home after the update.

        The day's own choice is kept. Naming who picks the child up means
        someone does, so a child who would leave alone is then picked up.
        """
        if new_pickup_person and self.activity_type in (
            ActivityType.SELF_DECIDER,
            ActivityType.SEND_HOME,
        ):
            return ActivityType.PICKED_UP_BY
        return self.activity_type

    def self_decider_end(self, new_exit_time: str | None) -> str | None:
        """The end of the window to leave in, kept unless the new start passes it."""
        end = _format_time_or_none(self.self_decider_end_time)
        if end is None or new_exit_time is None or end >= new_exit_time:
            return end
        return None


async def _day_templates(
    client: AulaApiClient, children: list[Child], target: datetime.date
) -> dict[int, DayTemplate]:
    """The planned day per child for ``target``; empty when Aula cannot say."""
    try:
        templates = await client.get_presence_templates([c.id for c in children], target, target)
    except Exception:
        return {}
    by_child: dict[int, DayTemplate] = {}
    for tmpl in templates:
        if tmpl.institution_profile and tmpl.institution_profile.id is not None:
            for dt in tmpl.day_templates:
                if dt.by_date and dt.by_date[:10] == target.isoformat():
                    by_child[tmpl.institution_profile.id] = dt
    return by_child


def _pickup_names(pickup_data: list[ChildPickupResponsibles]) -> list[str]:
    names: list[str] = []
    for pr in pickup_data:
        for person in pr.persons:
            label = f"{person.name} ({person.relation})" if person.relation else person.name
            if label not in names:
                names.append(label)
    return names


async def fetch_presence_now(
    client: AulaApiClient, children: list[Child], target: datetime.date
) -> PresenceNow:
    overviews: dict[int, DailyOverview] = {}
    for c in children:
        try:
            ov = await client.get_daily_overview(c.id)
            if ov:
                overviews[c.id] = ov
        except Exception as e:
            _LOGGER.warning("Could not fetch daily overview for %s: %s", c.name, e)

    pickup_data: list[ChildPickupResponsibles] = []
    try:
        pickup_data = await client.get_pickup_responsibles([c.id for c in children])
    except Exception as e:
        _LOGGER.warning("Could not fetch pickup responsibles: %s", e)

    return PresenceNow(
        overviews=overviews,
        templates=await _day_templates(client, children, target),
        pickup_names=_pickup_names(pickup_data),
    )


def current_plan(now: PresenceNow, child_id: int) -> CurrentPlan:
    """The child's plan: the day's template where there is one, else today's overview."""
    tmpl = now.templates.get(child_id)
    ov = now.overviews.get(child_id)
    return CurrentPlan(
        entry_time=(tmpl.entry_time if tmpl else None) or (ov.entry_time if ov else None),
        exit_time=(tmpl.exit_time or tmpl.self_decider_start_time if tmpl else None)
        or (ov.exit_time if ov else None),
        exit_with=(tmpl.exit_with if tmpl else None) or (ov.exit_with if ov else None),
        template_id=tmpl.id if tmpl else None,
        comment=tmpl.comment if tmpl else (ov.comment if ov else None),
        activity_type=_known_activity(tmpl.activity_type if tmpl else None),
        self_decider_end_time=tmpl.self_decider_end_time if tmpl else None,
    )


def _known_activity(value: int | None) -> ActivityType:
    try:
        return ActivityType(value)
    except ValueError:
        return ActivityType.PICKED_UP_BY


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

        now_state = await fetch_presence_now(client, children, target)
        overviews = now_state.overviews
        all_names = now_state.pickup_names

        # Show current state
        echo()
        print_heading(f"Current state ({target.isoformat()})")
        echo()
        for c in children:
            ov = overviews.get(c.id)
            tmpl = now_state.templates.get(c.id)

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
            location = ov.location.name if ov and ov.location else None

            echo(f"  {c.name}")
            echo(f"    Status:      {status_str}")
            if location:
                echo(f"    Location:    {location}")
            echo(f"    Checked in:  {check_in}")
            echo(f"    Checked out: {check_out}")
            echo(f"    Planned:     {planned_entry} - {planned_exit}")
            if cur_who:
                echo(f"    Pickup by:   {cur_who}")
            if cur_comment:
                echo(f"    Comment:     {cur_comment}")
            echo()

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
                now_state.templates = await _day_templates(client, children, target)

            # Pick a representative current state for defaults
            first_tmpl = next(
                (now_state.templates[c.id] for c in children if now_state.templates.get(c.id)),
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

            echo()
            entry_time = _prompt_time("Entry time", default=default_entry)
            exit_time = _prompt_time("Exit time", default=default_exit)

            if not entry_time and not exit_time:
                echo("  No changes specified.")
                return

            # Pickup person
            echo()
            if all_names:
                picked, ok = _prompt_pickup(all_names)
                if not ok:
                    return
                if picked is not None:
                    exit_with = picked

            # Comment
            comment_input = click.prompt("  Comment", default="", show_default=False).strip()
            if comment_input:
                comment = comment_input

            # Repeat
            echo()
            echo("  Repeat: 0=Never  1=Weekly  2=Every 2 weeks")
            repeat_choice = click.prompt("  Repeat", type=int, default=0)
            repeat_pattern = ["Never", "Weekly", "Every2Weeks"][min(repeat_choice, 2)]

            echo()

        # --- Resolve exit_with for non-interactive mode ---
        if not interactive:
            resolved, ok = _resolve_pickup(all_names, exit_with)
            if not ok:
                print_error(f"--exit-with {exit_with} is out of range (1-{len(all_names)})")
                return
            if resolved is not None:
                exit_with = resolved
            elif exit_with is None and all_names and not yes:
                picked, ok = _prompt_pickup(all_names)
                if not ok:
                    return
                if picked is not None:
                    exit_with = picked

        api_exit_with = _strip_relation(exit_with)
        if repeat_pattern is None:
            repeat_pattern = "Never"

        # Show planned changes
        print_heading(f"Changes for {target.isoformat()}")
        echo()

        echo(f"  {'Child':<30s}  {'Current':<25s}    {'New'}")
        echo(f"  {'-' * 30}  {'-' * 25}    {'-' * 25}")

        for c in children:
            plan = current_plan(now_state, c.id)
            new_entry = entry_time or _format_time(plan.entry_time)
            new_exit = exit_time or _format_time(plan.exit_time)
            new_who = api_exit_with if api_exit_with is not None else plan.exit_with

            current_str = f"{_format_time(plan.entry_time)}-{_format_time(plan.exit_time)}"
            if plan.exit_with:
                current_str += f" ({plan.exit_with})"

            new_str = f"{new_entry}-{new_exit}"
            if new_who:
                new_str += f" ({new_who})"

            echo(f"  {c.name:<30s}  {current_str:<25s} -> {new_str}")

        echo()

        if repeat_pattern.lower() != "never":
            echo(f"  Repeat: {repeat_pattern}")
        if comment:
            echo(f"  Comment: {comment}")
            echo()

        if not yes and not click.confirm("Apply these changes?"):
            echo("Cancelled.")
            return

        # Apply updates
        success_count = 0
        for c in children:
            plan = current_plan(now_state, c.id)
            final_exit = exit_time or (_format_time(plan.exit_time) if plan.exit_time else "16:00")
            activity = plan.activity_for(new_pickup_person=api_exit_with is not None)
            try:
                await client.update_presence_template(
                    institution_profile_id=c.id,
                    by_date=target,
                    entry_time=entry_time
                    or (_format_time(plan.entry_time) if plan.entry_time else "08:00"),
                    exit_time=final_exit,
                    activity_type=activity,
                    exit_with=api_exit_with if api_exit_with is not None else plan.exit_with,
                    comment=comment if comment is not None else plan.comment,
                    template_id=plan.template_id,
                    repeat_pattern=repeat_pattern,
                    self_decider_end_time=plan.self_decider_end(final_exit)
                    if activity is ActivityType.SELF_DECIDER
                    else None,
                )
                echo(f"  ✓ {c.name}")
                success_count += 1
            except Exception as e:
                echo(f"  ✗ {c.name}: {e}")

        echo()
        echo(f"Updated {success_count}/{len(children)} children.")


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
                _LOGGER.warning("Presence template has no institution profile")
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
                    echo(line)
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
                        echo(line)
                    echo()


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
            except ValueError, AttributeError:
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
                echo(f"  {day.date or 'Unknown date'}")
                if not day.activities:
                    echo("    (no activities)")
                else:
                    for act in day.activities:
                        time_range = ""
                        if act.start_time or act.end_time:
                            time_range = f" ({act.start_time or '?'} - {act.end_time or '?'})"
                        echo(f"    {act.title or 'Untitled'}{time_range}")
                echo()
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
                echo(f"  {name}: {status_text}")
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
            echo(
                "No institution on this account accepted the request. "
                "Institutions that do not use presence registrations reject it; "
                "try 'aula presence --states' instead."
            )
            return

        if output_json(ctx, [dict(r) for r in registrations]):
            return

        if not registrations:
            print_empty("presence registrations")
            return

        print_heading("Presence registrations")
        child_map = {c.id: c.name for c in prof.children}
        for reg in registrations:
            profile_id = reg.institution_profile_id
            if profile_id is None:
                name = "Unknown"
            else:
                name = child_map.get(profile_id, f"Profile {profile_id}")
            status_text = reg.status.display_name if reg.status else "Unknown"
            props: list[tuple[str, str | None]] = [("Child", name), ("Status", status_text)]
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
                    echo(line)
            echo()
