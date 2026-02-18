"""Download orchestration for gallery, post, and message images."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api_client import AulaApiClient

_LOGGER = logging.getLogger(__name__)

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

ProgressCallback = Callable[[str], object]


def sanitize_filename(name: str) -> str:
    """Replace filesystem-unsafe characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def _safe_display(text: str) -> str:
    """Strip characters that can't be displayed on the current console."""
    import sys

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding)


async def download_gallery_images(
    client: AulaApiClient,
    institution_profile_ids: list[int],
    output: Path,
    cutoff: date,
    tags: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[int, int]:
    """Download images from gallery albums.

    Returns (downloaded_count, skipped_count).
    """
    downloaded = 0
    skipped = 0

    if on_progress:
        on_progress("Fetching album list...")

    try:
        albums = await client.get_gallery_albums(institution_profile_ids)
    except Exception:
        _LOGGER.warning("Failed to fetch gallery albums", exc_info=True)
        return downloaded, skipped

    # Pre-filter: skip albums without id or before cutoff
    eligible = []
    for album in albums:
        album_id = album.get("id")
        if not album_id:
            continue
        creation_date_str = album.get("creationDate", "")
        album_date = _parse_date_str(creation_date_str)
        if album_date and album_date < cutoff:
            continue
        eligible.append(album)

    if on_progress:
        on_progress(f"Found {len(eligible)} albums (since {cutoff})")

    for album_idx, album in enumerate(eligible, 1):
        album_id = album.get("id")
        album_title = album.get("title", "Untitled")
        creation_date_str = album.get("creationDate", "")
        album_date = _parse_date_str(creation_date_str)

        if on_progress:
            on_progress(f"  Album {album_idx}/{len(eligible)}: {_safe_display(album_title)}")

        date_prefix = album_date.strftime("%Y%m%d") if album_date else "00000000"
        folder_name = sanitize_filename(f"{date_prefix} {album_title}")
        album_dir = output / "gallery" / folder_name

        try:
            pictures = await client.get_album_pictures(institution_profile_ids, album_id)
        except Exception:
            _LOGGER.warning("Failed to fetch pictures for album '%s'", album_title, exc_info=True)
            continue

        for pic in pictures:
            # Filter by tags if specified
            if tags:
                pic_tags = [t.get("name", "") for t in pic.get("tags", [])]
                if not any(tag in pic_tags for tag in tags):
                    continue

            file_info = pic.get("file") or {}
            url = file_info.get("url")
            filename = file_info.get("name", "image.jpg")
            if not url:
                continue

            dest = album_dir / sanitize_filename(filename)
            if dest.exists():
                skipped += 1
                continue

            try:
                data = await client.download_file(url)
                album_dir.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                downloaded += 1
            except Exception:
                _LOGGER.warning("Failed to download %s", url, exc_info=True)

    return downloaded, skipped


async def download_post_images(
    client: AulaApiClient,
    institution_profile_ids: list[int],
    output: Path,
    cutoff: date,
    on_progress: ProgressCallback | None = None,
) -> tuple[int, int]:
    """Download images from post attachments.

    Returns (downloaded_count, skipped_count).
    """
    downloaded = 0
    skipped = 0

    if on_progress:
        on_progress("Fetching posts...")

    all_posts = []
    page = 1
    while True:
        try:
            batch = await client.get_posts(institution_profile_ids, page=page, limit=100)
        except Exception:
            _LOGGER.warning("Failed to fetch posts page %d", page, exc_info=True)
            break
        if not batch:
            break
        all_posts.extend(batch)
        # Stop paginating if oldest post in batch is before cutoff
        oldest = batch[-1]
        if oldest.timestamp and oldest.timestamp.date() < cutoff:
            break
        page += 1

    # Filter to only posts with attachments
    eligible = [
        p for p in all_posts if p.timestamp and p.timestamp.date() >= cutoff and p.attachments
    ]

    if on_progress:
        on_progress(f"Found {len(eligible)} posts with attachments (since {cutoff})")

    for post_idx, post in enumerate(eligible, 1):
        if on_progress:
            on_progress(f"  Post {post_idx}/{len(eligible)}: {_safe_display(post.title)}")

        date_prefix = post.timestamp.strftime("%Y%m%d") if post.timestamp else "00000000"
        folder_name = sanitize_filename(f"{date_prefix} {post.title}")
        post_dir = output / "posts" / folder_name

        for attachment in post.attachments:
            media = attachment.get("media") or {}
            file_info = media.get("file") or {}
            url = file_info.get("url")
            filename = file_info.get("name")
            if not url or not filename:
                continue

            dest = post_dir / sanitize_filename(filename)
            if dest.exists():
                skipped += 1
                continue

            try:
                data = await client.download_file(url)
                post_dir.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                downloaded += 1
            except Exception:
                _LOGGER.warning("Failed to download %s", url, exc_info=True)

    return downloaded, skipped


async def download_message_images(
    client: AulaApiClient,
    children_institution_profile_ids: list[int],
    institution_codes: list[str],
    output: Path,
    cutoff: date,
    on_progress: ProgressCallback | None = None,
) -> tuple[int, int]:
    """Download attachments from messages using server-side search filtering.

    Returns (downloaded_count, skipped_count).
    """
    downloaded = 0
    skipped = 0

    if on_progress:
        on_progress("Searching for messages with attachments...")

    try:
        search_results = await client.search_messages(
            children_institution_profile_ids,
            institution_codes,
            from_date=cutoff,
            has_attachments=True,
        )
    except Exception:
        _LOGGER.warning("Failed to search messages", exc_info=True)
        return downloaded, skipped

    # Deduplicate by thread ID (search may return multiple results per thread)
    threads: dict[str, dict] = {}
    for result in search_results:
        raw = result._raw or {}
        thread_info = raw.get("thread", {})
        thread_id = str(thread_info.get("id", ""))
        if thread_id and thread_id not in threads:
            send_dt = raw.get("searchMessage", {}).get("sendDateTime", "")
            threads[thread_id] = {
                "subject": thread_info.get("subject", "No Subject"),
                "date": _parse_date_str(send_dt),
            }

    if on_progress:
        on_progress(f"Found {len(threads)} threads with attachments (since {cutoff})")

    for thread_idx, (thread_id, info) in enumerate(threads.items(), 1):
        subject = info["subject"]
        thread_date = info["date"]

        if on_progress:
            on_progress(f"  Thread {thread_idx}/{len(threads)}: {_safe_display(subject)}")

        date_prefix = thread_date.strftime("%Y%m%d") if thread_date else "00000000"
        folder_name = sanitize_filename(f"{date_prefix} {subject}")
        thread_dir = output / "messages" / folder_name

        try:
            messages = await client.get_all_messages_for_thread(thread_id)
        except Exception:
            _LOGGER.warning("Failed to fetch messages for thread '%s'", subject, exc_info=True)
            continue

        for msg in messages:
            # Filter messages by cutoff date
            msg_date = _parse_date_str(msg.get("sendDateTime", ""))
            if msg_date and msg_date < cutoff:
                continue

            if not msg.get("hasAttachments"):
                continue

            for attachment in msg.get("attachments") or []:
                file_info = attachment.get("file") or {}
                url = file_info.get("url")
                filename = file_info.get("name")
                if not url or not filename:
                    continue

                dest = thread_dir / sanitize_filename(filename)
                if dest.exists():
                    skipped += 1
                    continue

                try:
                    data = await client.download_file(url)
                    thread_dir.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    downloaded += 1
                except Exception:
                    _LOGGER.warning("Failed to download %s", url, exc_info=True)

    return downloaded, skipped


def _parse_date_str(date_str: str) -> date | None:
    """Parse an ISO date string to a date object, returning None on failure."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).date()
    except (ValueError, TypeError):
        return None
