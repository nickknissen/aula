"""Download orchestration for gallery, post, and message images."""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit

from ..api_client import AulaApiClient
from ..http import DownloadTooLargeError
from ..models.attachment import parse_attachments
from .diagnostics import credential_logger
from .mapping import get_in

_LOGGER = credential_logger(__name__)

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

ProgressCallback = Callable[[str], object]

DEFAULT_MAX_BYTES = 100 * 1024 * 1024


class DownloadCounts(NamedTuple):
    """Files downloaded, skipped as already exported, and failed."""

    downloaded: int
    skipped: int
    failed: int


class _Archive:
    """Remember source identity independently of display names and signed URLs."""

    def __init__(self, root: Path, max_bytes: int | None = DEFAULT_MAX_BYTES):
        self.root = root
        self.max_bytes = max_bytes
        self.manifest = root / ".aula-archive.json"
        self.downloaded = 0
        self.skipped = 0
        self.failed = 0
        self.files = self._load()

    def _load(self) -> dict[str, str]:
        if not self.manifest.exists():
            return {}
        try:
            files = json.loads(self.manifest.read_text())
            if not isinstance(files, dict):
                raise ValueError("manifest is not an object")
            return files
        except ValueError:
            aside = self.manifest.with_suffix(".json.corrupt")
            _LOGGER.warning(
                "Archive manifest %s is corrupt; moved to %s", self.manifest, aside, exc_info=True
            )
            self.manifest.replace(aside)
            return {}

    def counts(self) -> DownloadCounts:
        return DownloadCounts(self.downloaded, self.skipped, self.failed)

    async def try_save(
        self,
        client: AulaApiClient,
        folder: Path,
        filename: str,
        url: str,
        source: tuple,
        attachment_id: object = None,
        file_id: object = None,
    ) -> None:
        """Save one file and tally the outcome; a failure is counted, not raised."""
        try:
            if await self.save(client, folder, filename, url, source, attachment_id, file_id):
                self.downloaded += 1
            else:
                self.skipped += 1
        except DownloadTooLargeError:
            _LOGGER.warning("Skipped %s: larger than %s bytes", url, self.max_bytes)
            self.failed += 1
        except Exception:
            _LOGGER.warning("Failed to download %s", url, exc_info=True)
            self.failed += 1

    async def save(
        self,
        client: AulaApiClient,
        folder: Path,
        filename: str,
        url: str,
        source: tuple,
        attachment_id: object = None,
        file_id: object = None,
    ) -> bool:
        """Return True after downloading, False only for a recorded existing export."""
        # Stable IDs take precedence; query strings may rotate on every read.
        parts = urlsplit(url)
        fallback = (filename, urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))
        identity = (
            (*source, attachment_id, file_id) if attachment_id or file_id else (*source, fallback)
        )
        key = hashlib.sha256(json.dumps(identity, default=str).encode()).hexdigest()
        recorded = self.files.get(key)
        if recorded:
            dest = self.root / recorded
            if not dest.resolve().is_relative_to(self.root.resolve()):
                raise ValueError("Archive manifest contains a path outside the output directory")
            if dest.is_file():
                return False
        else:
            dest = folder / (sanitize_filename(filename) or "attachment")

        # A legacy file or another attachment is never proof of this export.
        original = dest
        suffix = 0
        while dest.exists():
            suffix += 1
            dest = original.with_name(f"{original.stem}-{key[:12]}-{suffix}{original.suffix}")

        data = await client.download_file(url, max_bytes=self.max_bytes)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("xb") as file:
            file.write(data)
        self.files[key] = str(dest.relative_to(self.root))
        temporary = self.manifest.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.files, indent=2))
        temporary.replace(self.manifest)
        return True


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
    max_bytes: int | None = DEFAULT_MAX_BYTES,
) -> DownloadCounts:
    """Download images from gallery albums."""
    archive = _Archive(output, max_bytes)

    if on_progress:
        on_progress("Fetching album list...")

    try:
        albums = await client.get_gallery_albums(institution_profile_ids)
    except Exception:
        _LOGGER.warning("Failed to fetch gallery albums", exc_info=True)
        archive.failed += 1
        return archive.counts()

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

        if not isinstance(album_id, int):
            continue

        try:
            pictures = await client.get_album_pictures(institution_profile_ids, album_id)
        except Exception:
            _LOGGER.warning("Failed to fetch pictures for album %s", album_id, exc_info=True)
            archive.failed += 1
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

            await archive.try_save(
                client,
                album_dir,
                filename,
                url,
                ("gallery", album_id),
                pic.get("id"),
                file_info.get("id"),
            )

    return archive.counts()


async def download_post_images(
    client: AulaApiClient,
    institution_profile_ids: list[int],
    output: Path,
    cutoff: date,
    on_progress: ProgressCallback | None = None,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
) -> DownloadCounts:
    """Download images from post attachments."""
    archive = _Archive(output, max_bytes)

    if on_progress:
        on_progress("Fetching posts...")

    all_posts = []
    page = 1
    while True:
        try:
            batch = await client.get_posts(institution_profile_ids, page=page, limit=100)
        except Exception:
            _LOGGER.warning("Failed to fetch posts page %d", page, exc_info=True)
            archive.failed += 1
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
            # A post can also attach a plain file or a link; only media is an image.
            if attachment.media is None or attachment.file is None:
                continue
            url = attachment.file.url
            filename = attachment.file.name
            if not url or not filename:
                continue

            await archive.try_save(
                client,
                post_dir,
                filename,
                url,
                ("posts", post.id),
                attachment.id,
                attachment.file.id,
            )

    return archive.counts()


async def download_message_images(
    client: AulaApiClient,
    children_institution_profile_ids: list[int],
    institution_codes: list[str],
    output: Path,
    cutoff: date,
    on_progress: ProgressCallback | None = None,
    on_incomplete: ProgressCallback | None = None,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
) -> DownloadCounts:
    """Download attachments from messages using server-side search filtering.

    Incomplete pagination is logged, sent to on_progress, and reported through
    on_incomplete when provided.
    """
    archive = _Archive(output, max_bytes)

    def incomplete(reason: str) -> None:
        _LOGGER.warning("Incomplete message export: %s", reason)
        if on_progress:
            on_progress(f"Incomplete message export: {reason}")
        if on_incomplete:
            on_incomplete(reason)

    if on_progress:
        on_progress("Searching for messages with attachments...")

    try:
        search_result = await client.search_messages_result(
            children_institution_profile_ids,
            institution_codes,
            from_date=cutoff,
            has_attachments=True,
        )
    except Exception:
        _LOGGER.warning("Failed to search messages", exc_info=True)
        incomplete("search:request_failed")
        archive.failed += 1
        return archive.counts()

    if not search_result.complete:
        incomplete(f"search:{search_result.termination_reason}")
    search_results = search_result.items

    # Deduplicate by thread ID (search may return multiple results per thread)
    threads: dict[str, dict] = {}
    for result in search_results:
        raw = result._raw or {}
        thread_id = str(get_in(raw, "thread.id", default=""))
        if thread_id and thread_id not in threads:
            send_dt = get_in(raw, "searchMessage.sendDateTime", default="")
            threads[thread_id] = {
                "subject": get_in(raw, "thread.subject", default="No Subject"),
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
            message_result = await client.get_all_messages_for_thread_result(thread_id)
        except Exception:
            _LOGGER.warning("Failed to fetch messages for thread %s", thread_id, exc_info=True)
            incomplete(f"thread:{thread_id}:request_failed")
            archive.failed += 1
            continue

        if not message_result.complete:
            incomplete(f"thread:{thread_id}:{message_result.termination_reason}")
        messages = message_result.items

        for msg in messages:
            # Filter messages by cutoff date
            msg_date = _parse_date_str(msg.get("sendDateTime", ""))
            if msg_date and msg_date < cutoff:
                continue

            if not msg.get("hasAttachments"):
                continue

            for attachment in parse_attachments(msg.get("attachments")):
                if attachment.file is None:
                    continue
                url = attachment.file.url
                filename = attachment.file.name
                if not url or not filename:
                    continue

                await archive.try_save(
                    client,
                    thread_dir,
                    filename,
                    url,
                    ("messages", thread_id, msg.get("id") or msg.get("sendDateTime")),
                    attachment.id,
                    attachment.file.id,
                )

    return archive.counts()


def _parse_date_str(date_str: str) -> date | None:
    """Parse an ISO date string to a date object, returning None on failure."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).date()
    except ValueError, TypeError:
        return None
