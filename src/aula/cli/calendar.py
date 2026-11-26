import datetime
from typing import Any
from zoneinfo import ZoneInfo

import click

from ..models import (
    Profile,
)
from ..utils.output import (
    echo,
    format_calendar_context_lines,
    format_row,
    output_json,
    print_empty,
    print_error,
    print_heading,
)
from ._app import _get_client, async_cmd, cli


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
                    echo(format_row(key, str(event[key])))
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
            echo(line)

        if not events:
            print_empty("calendar events")
            return

        from ..utils.table import build_calendar_table, print_calendar_table

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
            echo(format_row(title, date_str))


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
                if child.institution_code and child.institution_code not in institution_codes:
                    institution_codes.append(child.institution_code)

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
            echo(format_row(name, bday))


@cli.command("vacations")
@click.pass_context
@async_cmd
async def vacations(ctx):
    """Show vacation registrations."""
    async with await _get_client(ctx) as client:
        try:
            prof = await client.get_profile()
        except Exception as e:
            print_error(f"fetching profile: {e}")
            return

        child_ids = [c.id for c in prof.children]
        if not child_ids:
            print_error("no children on this profile to look up vacation registrations for")
            return

        try:
            result = await client.get_vacation_registrations(child_ids)
        except Exception as e:
            print_error(f"fetching vacations: {e}")
            return

        if output_json(ctx, [dict(v) for v in result]):
            return

        if not result:
            print_empty("vacation registrations")
            return

        print_heading("Vacation Registrations")
        for v in result:
            parts = []
            if v.title:
                parts.append(v.title)
            if v.is_missing_answer:
                parts.append("[missing answer]")
            echo(format_row(v.child_name or f"Child {v.child_id}", *parts))
            dates = []
            if v.start_date:
                dates.append(f"From: {v.start_date}")
            if v.end_date:
                dates.append(f"To: {v.end_date}")
            if dates:
                echo(f"  {' | '.join(dates)}")
            if v.response_deadline:
                echo(f"  Answer by: {v.response_deadline}")
            if v.note_to_guardian:
                echo(f"  Note: {v.note_to_guardian}")


@cli.command("meetings")
@click.option(
    "--child-id", type=int, multiple=True, help="Child institution profile ID; repeatable."
)
@click.option("--start-date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Exclusive end date. Defaults to 100 days after the start date.",
)
@click.pass_context
@async_cmd
async def meetings(ctx, child_id, start_date, end_date):
    """Show booked parent meetings for children, from today by default."""
    zone = ZoneInfo("Europe/Copenhagen")
    start = (
        start_date.replace(tzinfo=zone)
        if start_date
        else datetime.datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    end = end_date.replace(tzinfo=zone) if end_date else start + datetime.timedelta(days=100)
    if end <= start:
        raise click.BadParameter("must be after the start date", param_hint="--end-date")
    async with await _get_client(ctx) as client:
        try:
            profile = await client.get_profile()
            children = [child for child in profile.children if not child_id or child.id in child_id]
            unknown = set(child_id) - {child.id for child in profile.children}
            if unknown:
                raise click.BadParameter(
                    f"unknown child ID(s): {', '.join(map(str, sorted(unknown)))}",
                    param_hint="--child-id",
                )
            rows: list[dict[str, Any]] = []
            for child in children:
                bookings = await client.get_meeting_bookings(child.id, start, end)
                rows.extend({**dict(booking), "child_name": child.name} for booking in bookings)
        except click.BadParameter:
            raise
        except Exception as exc:
            raise click.ClickException(f"fetching booked meetings: {exc}") from exc

    rows.sort(key=lambda row: row["start_datetime"])
    if output_json(ctx, rows):
        return
    if not rows:
        print_empty("booked meetings")
        return
    print_heading("Booked meetings")
    for row in rows:
        beginning = row["start_datetime"].astimezone(zone)
        ending = row["end_datetime"].astimezone(zone)
        echo(f"{row['child_name']}: {row['title']}")
        echo(f"  {beginning:%Y-%m-%d %H:%M %Z} – {ending:%Y-%m-%d %H:%M %Z}")
        if row["location"]:
            echo(f"  Location: {row['location']}")
