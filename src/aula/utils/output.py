"""Shared helpers for consistent human-readable CLI output."""

import datetime
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from aula.models.notification import Notification


def format_heading_lines(title: str) -> list[str]:
    """Return heading lines with a title and matching underline."""
    normalized = title.strip()
    return [normalized, "=" * len(normalized)]


def print_heading(title: str) -> None:
    """Print a consistent heading block."""
    for line in format_heading_lines(title):
        click.echo(line)


def print_empty(resource: str) -> None:
    """Print the shared empty-state sentence."""
    click.echo(f"No {resource} found.")


def print_error(message: str) -> None:
    """Print the shared error sentence."""
    click.echo(f"Error: {message}")


def clip(text: str, max_len: int = 120) -> str:
    """Clip long text with ellipsis for compact output rows."""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return "." * max_len
    return f"{text[: max_len - 3].rstrip()}..."


def format_row(primary: str, secondary: str | None = None, tertiary: str | None = None) -> str:
    """Format a row as 'primary | secondary | tertiary' while skipping blanks."""
    parts = [primary]
    for value in (secondary, tertiary):
        if value and value.strip():
            parts.append(value.strip())
    return " | ".join(parts)


def format_message_lines(
    title: str,
    sender: str,
    send_date: str,
    content: str,
    fallback_title: str | None = None,
    include_title: bool = True,
) -> list[str]:
    """Format a message as title plus indented metadata/body lines."""
    resolved_title = title.strip() or (fallback_title.strip() if fallback_title else "")
    lines: list[str] = []
    if include_title:
        lines.append(clip(resolved_title) if resolved_title else "(No subject)")
    lines.append(f"  Author: {sender}")
    if send_date.strip():
        lines.append(f"  Date: {send_date}")

    body = content.strip()
    lines.append("  Body:")
    if body:
        lines.extend(f"  {clip(line)}" for line in body.splitlines())
    else:
        lines.append("  (no message body)")
    return lines


def format_notification_lines(
    item: "Notification", institution_names: dict[str, str] | None = None
) -> list[str]:
    """Format a notification as a compact multi-line block."""
    read_flag = None
    if item.is_read is True:
        read_flag = "Read"
    elif item.is_read is False:
        read_flag = "Unread"

    lines = [clip(item.title)]
    if read_flag:
        lines.append(f"  Status: {read_flag}")

    if item.module:
        lines.append(f"  Module: {item.module}")
    if item.event_type:
        lines.append(f"  Event: {item.event_type}")
    if item.notification_type:
        lines.append(f"  Type: {item.notification_type}")

    if item.created_at:
        lines.append(f"  Triggered: {item.created_at}")
    if item.expires_at:
        lines.append(f"  Expires: {item.expires_at}")

    institution_label: str | None = None
    if item.institution_code:
        institution_label = item.institution_code
        if institution_names:
            institution_label = institution_names.get(item.institution_code, item.institution_code)
    if institution_label:
        lines.append(f"  Institution: {institution_label}")
    if item.related_child_name:
        lines.append(f"  Child: {item.related_child_name}")

    if item.post_id is not None:
        lines.append(f"  Post: {item.post_id}")
    if item.album_id is not None:
        lines.append(f"  Album: {item.album_id}")
    if item.media_id is not None:
        lines.append(f"  Media: {item.media_id}")

    return lines


def format_post_lines(
    title: str,
    author: str,
    date: str,
    body: str,
    attachments_count: int,
) -> list[str]:
    """Format a post as title plus indented metadata/body lines."""
    lines = [clip(title) if title.strip() else "(No title)"]
    if author.strip():
        lines.append(f"  Author: {author}")
    if date.strip():
        lines.append(f"  Date: {date}")

    body_text = body.strip()
    lines.append("  Body:")
    if body_text:
        lines.extend(f"  {clip(line)}" for line in body_text.splitlines())
    else:
        lines.append("  (no post body)")

    if attachments_count > 0:
        lines.append(f"  Attachments: {attachments_count}")

    return lines


def format_calendar_context_lines(
    start_date: datetime.datetime,
    end_date: datetime.datetime,
    profile_count: int,
) -> list[str]:
    """Format calendar query context lines."""
    return [
        f"  Start: {start_date.strftime('%Y-%m-%d')}",
        f"  End: {end_date.strftime('%Y-%m-%d')}",
        f"  Profiles: {profile_count}",
    ]
