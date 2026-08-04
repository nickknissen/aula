"""Shared helpers for consistent human-readable CLI output."""

import datetime
from typing import Any, NamedTuple

import click

from ..models.notification import Notification
from .json import to_json


def output_json(ctx: click.Context, data: Any) -> bool:
    """If ``--output json`` is active, emit JSON and return ``True``."""
    if ctx.obj.get("OUTPUT_FORMAT") == "json":
        click.echo(to_json(data))
        return True
    return False


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


class ContactRow(NamedTuple):
    """One child-guardian pairing, ready to render as a table row."""

    child: str
    guardian: str
    relation: str
    class_name: str
    phone: str
    address: str


def build_contact_rows(item: dict[str, Any]) -> list[ContactRow]:
    """Build child-guardian rows for one contact.

    Aula returns a contact plus its ``relations``: a guardian carries their
    children, a child carries their guardians. Either way the pairing is
    rendered child-first, so one contact can yield several rows. A guardian's
    children from other groups are included, since the relation list is not
    scoped to the queried group; the class column tells them apart.

    Phone and address always describe the *guardian*, read from whichever object
    that is - the contact itself in a guardian listing, the relation in a child
    listing. Child relations carry their own contact details, so taking them
    from the wrong side would show the child's registered number instead. Cells
    stay empty when the profile hides its contact information.

    Contacts with no usable relations (employees, or profiles whose relations
    are hidden) yield a single row with the role in place of the relation.
    """
    name = str(item.get("fullName") or item.get("name") or "Unknown")
    role = str(item.get("role") or item.get("portalRole") or "")
    relations = [r for r in (item.get("relations") or []) if isinstance(r, dict)]

    if role == "guardian":
        # ``relation`` on each child says how this guardian relates to them.
        children = [r for r in relations if r.get("role") == "child"]
        if children:
            return [
                ContactRow(
                    child=_contact_name(child),
                    guardian=name,
                    relation=_relation_of(child),
                    class_name=_class_of(child),
                    phone=_phone_of(item),
                    address=_address_of(item),
                )
                for child in children
            ]

    elif role == "child":
        guardians = [r for r in relations if r.get("role") == "guardian"]
        if guardians:
            return [
                ContactRow(
                    child=name,
                    guardian=_contact_name(guardian),
                    relation=_relation_of(guardian),
                    class_name=_class_of(item),
                    phone=_phone_of(guardian),
                    address=_address_of(guardian),
                )
                for guardian in guardians
            ]

    return [
        ContactRow(
            child=name,
            guardian="",
            relation=role,
            class_name=_class_of(item),
            phone=_phone_of(item),
            address=_address_of(item),
        )
    ]


#: Column layout for a listing where every row pairs a child with a guardian.
PAIRED_CONTACT_HEADERS = ["Child", "Guardian", "Relation", "Class", "Phone", "Address"]
#: Column layout for a listing with no relations to pair (employees).
FLAT_CONTACT_HEADERS = ["Name", "Role", "Details", "Phone", "Address"]


def build_contact_table(
    contacts: list[dict[str, Any]],
) -> tuple[list[str], list[tuple[str, ...]]]:
    """Build ``(headers, rows)`` for a contact listing, sorted child-first.

    Employee listings carry no relations, so they collapse to a flatter layout
    rather than showing an empty Guardian column.
    """
    rows = sort_contact_rows([row for item in contacts for row in build_contact_rows(item)])

    if any(item.get("relations") for item in contacts):
        return PAIRED_CONTACT_HEADERS, [tuple(row) for row in rows]

    return FLAT_CONTACT_HEADERS, [
        (row.child, row.relation, row.class_name, row.phone, row.address) for row in rows
    ]


#: Danish sorts Æ, Ø, Å after Z, in that order; plain code points disagree (Å < Æ < Ø).
_DANISH_LETTER_ORDER = str.maketrans({"æ": "zz1", "ø": "zz2", "å": "zz3"})


def danish_sort_key(text: str) -> str:
    """Case-insensitive sort key that places Æ, Ø and Å last, as Danish does."""
    return text.casefold().translate(_DANISH_LETTER_ORDER)


def sort_contact_rows(rows: list[ContactRow]) -> list[ContactRow]:
    """Sort contact rows by child name, then guardian name."""
    return sorted(rows, key=lambda row: (danish_sort_key(row.child), danish_sort_key(row.guardian)))


def scope_relations_to_children(
    contacts: list[dict[str, Any]],
    group_children: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop child relations that belong to another group.

    A guardian's ``relations`` list carries every child they have, not just the
    ones in the queried group, so a class listing would otherwise show siblings
    from other classes. ``group_children`` is the same group fetched with the
    ``child`` filter; its ``id`` values are institution profile IDs and match
    the ``id`` on each relation.

    Guardians left without a single child in the group are dropped entirely.
    Returns ``contacts`` unchanged when the group has no children at all (a
    parents-only group), since there is nothing to scope against.
    """
    child_ids = {child.get("id") for child in group_children if child.get("id") is not None}
    if not child_ids:
        return contacts

    scoped: list[dict[str, Any]] = []
    for item in contacts:
        relations = [r for r in (item.get("relations") or []) if isinstance(r, dict)]
        if not relations:
            scoped.append(item)
            continue

        kept = [r for r in relations if r.get("role") != "child" or r.get("id") in child_ids]
        had_children = any(r.get("role") == "child" for r in relations)
        if had_children and not any(r.get("role") == "child" for r in kept):
            continue
        scoped.append({**item, "relations": kept})
    return scoped


def _contact_name(entry: dict[str, Any]) -> str:
    """Return a contact or relation's display name."""
    return str(entry.get("fullName") or entry.get("name") or "Unknown")


def _relation_of(entry: dict[str, Any]) -> str:
    """Return the guardian relation (``Far``/``Mor``) carried by ``entry``."""
    return str(entry.get("relation") or "").strip()


def _class_of(entry: dict[str, Any]) -> str:
    """Return a contact's class/metadata label (e.g. ``3.1``)."""
    return str(entry.get("metadata") or "").strip()


def _phone_of(entry: dict[str, Any]) -> str:
    """Return the best available phone number, preferring mobile.

    Hidden or unset numbers come back as ``None`` or an empty string, so both
    are skipped.
    """
    for key in ("mobilePhoneNumber", "homePhoneNumber", "workPhoneNumber"):
        number = str(entry.get(key) or "").strip()
        if number:
            return number
    return ""


def _address_of(entry: dict[str, Any]) -> str:
    """Format a contact's address as ``street, postcode district``.

    Any missing part is dropped rather than leaving a stray comma; profiles with
    an unknown address carry the literal street ``Ukendt``.
    """
    address = entry.get("address")
    if not isinstance(address, dict):
        return ""

    street = str(address.get("street") or "").strip()
    postal_code = str(address.get("postalCode") or "").strip()
    district = str(address.get("postalDistrict") or "").strip()
    city = " ".join(part for part in (postal_code, district) if part)
    return ", ".join(part for part in (street, city) if part)


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
    item: Notification,
    institution_names: dict[str, str] | None = None,
    album_names: dict[int, str] | None = None,
) -> list[str]:
    """Format a notification as a compact multi-line block."""
    lines = [clip(item.title)]

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
        album_label = str(item.album_id)
        if album_names:
            album_label = album_names.get(item.album_id, album_label)
        lines.append(f"  Album: {album_label}")
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


def format_record_lines(
    title: str,
    properties: list[tuple[str, str | None]] | None = None,
    body_lines: list[str] | None = None,
    body_label: str | None = None,
    empty_body_text: str | None = None,
) -> list[str]:
    """Format a generic title + properties + optional body block."""
    lines = [clip(title) if title.strip() else "(No title)"]

    for label, value in properties or []:
        if value and value.strip():
            lines.append(f"  {label}: {value.strip()}")

    if body_label:
        lines.append(f"  {body_label}:")

    normalized_body = [clip(line) for line in (body_lines or []) if line.strip()]
    if normalized_body:
        lines.extend(f"  {line}" for line in normalized_body)
    elif body_label and empty_body_text:
        lines.append(f"  {empty_body_text}")

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


def format_report_intro_lines(title: str, properties: list[tuple[str, str]]) -> list[str]:
    """Format a report intro as title + key-value lines."""
    lines = [title.strip()]
    for key, value in properties:
        lines.append(f"  {key}: {value}")
    return lines
