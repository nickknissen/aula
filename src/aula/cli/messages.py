import click

from ..api_client import ThreadScanLimitError
from ..http import HttpRequestError
from ..models import (
    Message,
    MessageThread,
    Notification,
    Profile,
)
from ..utils.json import to_json
from ..utils.mapping import get_in
from ..utils.output import (
    clip,
    echo,
    format_message_lines,
    format_notification_lines,
    format_row,
    output_json,
    print_empty,
    print_error,
    print_heading,
)
from ._app import _get_client, async_cmd, cli
from ._helpers import _thread_meta


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
            except HttpRequestError as e:
                print_error(f"fetching message folders: {e}")
                return

            if output_json(ctx, [dict(f) for f in folder_list]):
                return

            if not folder_list:
                print_empty("message folders")
                return

            print_heading("Message Folders")
            for f in folder_list:
                echo(format_row(f.name, f"ID {f.id}"))
            return

        if search:
            try:
                prof: Profile = await client.get_profile()
            except (HttpRequestError, ValueError) as e:
                print_error(f"fetching profile: {e}")
                return

            institution_codes: list[str] = []
            for child in prof.children:
                if child.institution_code and child.institution_code not in institution_codes:
                    institution_codes.append(child.institution_code)

            try:
                search_result = await client.search_messages_result(
                    text=search,
                    institution_profile_ids=[child.id for child in prof.children],
                    institution_codes=institution_codes,
                    limit=limit,
                )
            except (HttpRequestError, ValueError) as e:
                print_error(f"searching messages: {e}")
                return

            results = search_result.items
            if output_json(
                ctx,
                {
                    "items": [
                        {
                            **dict(m),
                            "thread_id": get_in(m._raw or {}, "thread.id"),
                            "subject": get_in(m._raw or {}, "thread.subject", default=""),
                        }
                        for m in results
                    ],
                    "complete": search_result.complete,
                    "termination_reason": search_result.termination_reason,
                },
            ):
                if not search_result.complete:
                    ctx.exit(1)
                return

            if not search_result.complete:
                echo(f"Incomplete message search: {search_result.termination_reason}", err=True)

            if not results:
                print_empty("messages")
                if not search_result.complete:
                    ctx.exit(1)
                return

            print_heading(f'Messages: "{search}"')

            for i, msg in enumerate(results):
                msg_raw = msg._raw or {}
                sender = msg.sender_name or "Unknown"
                send_date = get_in(msg_raw, "searchMessage.sendDateTime", default="")
                subject = get_in(msg_raw, "thread.subject", default="")

                for line in format_message_lines(subject, sender, send_date, msg.content):
                    echo(line)

                if i < len(results) - 1:
                    echo()
            if not search_result.complete:
                ctx.exit(1)
            return

        try:
            filter_on = "unread" if unread else None
            threads: list[MessageThread] = await client.get_message_threads(filter_on=filter_on)
            threads = threads[:limit]
        except HttpRequestError as e:
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
                except HttpRequestError:
                    t["messages"] = []
                json_threads.append(t)
            echo(to_json(json_threads))
            return

        filter_label = "unread" if unread else "latest"
        print_heading(f"Message threads: {filter_label}")

        if not threads:
            print_empty("message threads")
            return

        for i, thread in enumerate(threads):
            echo(clip(thread.subject))
            if meta := _thread_meta(thread):
                echo(f"  {clip(meta)}")
            if thread.web_url:
                echo(f"  Link: {thread.web_url}")

            try:
                messages_list: list[Message] = await client.get_messages_for_thread(
                    thread.thread_id
                )
                if not messages_list:
                    echo("  (no messages)")
                else:
                    for msg in messages_list:
                        msg_raw = msg._raw or {}
                        sender = get_in(msg_raw, "sender.fullName", default="Unknown")
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
                            echo(f"{line}")
            except HttpRequestError as e:
                print_error(str(e))

            if i < len(threads) - 1:
                echo()


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
                code = child.institution_code
                if not code:
                    continue
                if child.institution_name and code not in institution_names:
                    institution_names[code] = child.institution_name
                if code not in institution_codes:
                    institution_codes.append(code)
        except HttpRequestError, ValueError:
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
        except HttpRequestError as e:
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
            except HttpRequestError:
                pass

        heading = f"Notifications ({len(items)})"
        print_heading(heading)

        # Group by event type and show summary
        groups: dict[str, list[Notification]] = {}
        for item in items:
            key = item.event_type or "Unknown"
            groups.setdefault(key, []).append(item)

        echo("Summary:")
        for event_type, group_items in sorted(groups.items(), key=lambda x: -len(x[1])):
            echo(f"  {event_type}: {len(group_items)}")
        echo()

        for event_type, group_items in sorted(groups.items(), key=lambda x: -len(x[1])):
            echo(f"── {event_type} ({len(group_items)}) ──")
            for i, item in enumerate(group_items):
                for line in format_notification_lines(
                    item, institution_names=institution_names, album_names=album_names
                ):
                    echo(line)

                if i < len(group_items) - 1:
                    echo()
            echo()


@cli.command("auto-reply")
@click.pass_context
@async_cmd
async def auto_reply(ctx):
    """Show current auto-reply status."""
    async with await _get_client(ctx) as client:
        try:
            result = await client.get_auto_reply()
        except HttpRequestError as e:
            print_error(f"fetching auto-reply: {e}")
            return

        if result is None:
            print_empty("auto-reply configuration")
            return

        if output_json(ctx, dict(result)):
            return

        print_heading("Auto-Reply")
        echo(format_row("Enabled", "Yes" if result.is_enabled else "No"))
        if result.message:
            echo(format_row("Message", result.message))
        if result.start_date:
            echo(format_row("From", result.start_date))
        if result.end_date:
            echo(format_row("Until", result.end_date))


@cli.command("mark-read")
@click.argument("thread_ids", nargs=-1, required=True)
@click.pass_context
@async_cmd
async def mark_read(ctx, thread_ids):
    """Mark message threads as read.

    Writes to Aula: each thread is read up to and including its latest message, as if
    it had been opened in the app. Thread IDs are the ones `aula messages` shows. Only
    threads in your own mailbox are handled. Exits non-zero when any thread could not
    be marked, after trying all of them.

    Examples:

      aula mark-read 100001

      aula mark-read 100002 100003
    """
    is_json = bool(ctx.obj) and ctx.obj.get("OUTPUT_FORMAT") == "json"
    results: list[dict] = []
    async with await _get_client(ctx) as client:
        for thread_id in thread_ids:
            try:
                marked = await client.mark_thread_read(thread_id)
            except (HttpRequestError, ValueError, ThreadScanLimitError) as e:
                print_error(f"marking thread {thread_id} as read: {e}", err=is_json)
                marked = False
            results.append({"thread_id": thread_id, "marked": marked})

    if not output_json(ctx, results):
        for r in results:
            echo(f"  {'✓' if r['marked'] else '✗'} {r['thread_id']}")

    if not all(r["marked"] for r in results):
        ctx.exit(1)
