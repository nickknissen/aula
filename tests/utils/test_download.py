"""Tests for aula.utils.download."""

import json
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aula.http import DownloadTooLargeError
from aula.models.attachment import Attachment
from aula.models.message import Message
from aula.models.pagination import PaginationResult
from aula.utils.download import (
    _parse_date_str,
    download_gallery_images,
    download_message_images,
    download_post_images,
    sanitize_filename,
)


class TestSanitizeFilename:
    """Tests for sanitize_filename."""

    def test_replaces_unsafe_characters(self):
        assert sanitize_filename('file<>:"/\\|?*name') == "file_________name"

    def test_leaves_safe_characters(self):
        assert sanitize_filename("normal file (1).jpg") == "normal file (1).jpg"

    def test_strips_whitespace(self):
        assert sanitize_filename("  hello  ") == "hello"

    def test_empty_string(self):
        assert sanitize_filename("") == ""


class TestParseDateStr:
    """Tests for _parse_date_str."""

    def test_iso_date(self):
        assert _parse_date_str("2026-03-01T10:00:00") == date(2026, 3, 1)

    def test_iso_date_with_tz(self):
        assert _parse_date_str("2026-03-01T10:00:00+01:00") == date(2026, 3, 1)

    def test_empty_string(self):
        assert _parse_date_str("") is None

    def test_invalid_string(self):
        assert _parse_date_str("not-a-date") is None


def _make_mock_client():
    """Create a mock AulaApiClient with common methods."""
    client = AsyncMock()
    client.get_gallery_albums = AsyncMock(return_value=[])
    client.get_album_pictures = AsyncMock(return_value=[])
    client.get_posts = AsyncMock(return_value=[])
    client.search_messages = AsyncMock(return_value=[])
    client.get_all_messages_for_thread = AsyncMock(return_value=[])

    async def search_result(*args, **kwargs):
        return PaginationResult(await client.search_messages(*args, **kwargs), True, "exhausted")

    async def thread_result(*args, **kwargs):
        return PaginationResult(
            await client.get_all_messages_for_thread(*args, **kwargs), True, "exhausted"
        )

    client.search_messages_result = AsyncMock(side_effect=search_result)
    client.get_all_messages_for_thread_result = AsyncMock(side_effect=thread_result)
    client.download_file = AsyncMock(return_value=b"image-data")
    return client


class TestDownloadGalleryImages:
    """Tests for download_gallery_images."""

    @pytest.mark.asyncio
    async def test_downloads_images(self, tmp_path):
        """Downloads images and creates correct folder structure."""
        client = _make_mock_client()
        client.get_gallery_albums.return_value = [
            {"id": 1, "title": "Trip", "creationDate": "2026-03-01T12:00:00"},
        ]
        client.get_album_pictures.return_value = [
            {"file": {"url": "http://example.com/pic.jpg", "name": "pic.jpg"}, "tags": []},
        ]

        downloaded, skipped, _ = await download_gallery_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 1
        assert skipped == 0
        assert (tmp_path / "gallery" / "20260301 Trip" / "pic.jpg").exists()

    @pytest.mark.asyncio
    async def test_skips_albums_before_cutoff(self, tmp_path):
        """Albums before cutoff date are skipped."""
        client = _make_mock_client()
        client.get_gallery_albums.return_value = [
            {"id": 1, "title": "Old", "creationDate": "2025-01-01T12:00:00"},
        ]

        downloaded, skipped, _ = await download_gallery_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 0
        client.get_album_pictures.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preserves_untracked_legacy_files(self, tmp_path):
        """A legacy filename cannot prove which source attachment was exported."""
        client = _make_mock_client()
        client.get_gallery_albums.return_value = [
            {"id": 1, "title": "Trip", "creationDate": "2026-03-01T12:00:00"},
        ]
        client.get_album_pictures.return_value = [
            {"file": {"url": "http://example.com/pic.jpg", "name": "pic.jpg"}, "tags": []},
        ]

        # Pre-create the file
        dest_dir = tmp_path / "gallery" / "20260301 Trip"
        dest_dir.mkdir(parents=True)
        (dest_dir / "pic.jpg").write_bytes(b"existing")

        downloaded, skipped, _ = await download_gallery_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 1
        assert skipped == 0
        assert (dest_dir / "pic.jpg").read_bytes() == b"existing"
        assert len(list(dest_dir.glob("*.jpg"))) == 2

    @pytest.mark.asyncio
    async def test_tag_filtering(self, tmp_path):
        """Only pictures with matching tags are downloaded."""
        client = _make_mock_client()
        client.get_gallery_albums.return_value = [
            {"id": 1, "title": "Trip", "creationDate": "2026-03-01T12:00:00"},
        ]
        client.get_album_pictures.return_value = [
            {
                "file": {"url": "http://example.com/a.jpg", "name": "a.jpg"},
                "tags": [{"name": "child1"}],
            },
            {
                "file": {"url": "http://example.com/b.jpg", "name": "b.jpg"},
                "tags": [{"name": "child2"}],
            },
        ]

        downloaded, skipped, _ = await download_gallery_images(
            client, [100], tmp_path, date(2026, 1, 1), tags=["child1"]
        )

        assert downloaded == 1

    @pytest.mark.asyncio
    async def test_handles_api_failure(self, tmp_path):
        """API failure for album list downloads nothing and counts as failed."""
        client = _make_mock_client()
        client.get_gallery_albums.side_effect = RuntimeError("API down")

        counts = await download_gallery_images(client, [100], tmp_path, date(2026, 1, 1))

        assert counts == (0, 0, 1)


class TestDownloadPostImages:
    """Tests for download_post_images."""

    def _make_post(self, *, id, title, timestamp_str, attachments=None):
        """Create a mock Post object."""
        post = MagicMock()
        post.id = id
        post.title = title
        post.timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else None
        post.attachments = attachments or []
        return post

    @pytest.mark.asyncio
    async def test_downloads_post_attachments(self, tmp_path):
        """Downloads attachments from posts with correct folder structure."""
        client = _make_mock_client()
        post = self._make_post(
            id=10,
            title="School Trip",
            timestamp_str="2026-03-01T10:00:00+01:00",
            attachments=[
                Attachment.from_dict(
                    {
                        "media": {
                            "file": {"url": "http://example.com/photo.jpg", "name": "photo.jpg"}
                        }
                    }
                ),
            ],
        )
        client.get_posts.side_effect = [[post], []]

        downloaded, skipped, _ = await download_post_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 1
        assert (tmp_path / "posts" / "20260301 School Trip" / "photo.jpg").exists()

    @pytest.mark.asyncio
    async def test_skips_non_media_attachments(self, tmp_path):
        """A post can attach a PDF or a link, neither of which is an image."""
        client = _make_mock_client()
        post = self._make_post(
            id=11,
            title="Week Plan",
            timestamp_str="2026-03-01T10:00:00+01:00",
            attachments=[
                Attachment.from_dict(
                    {
                        "name": "plan.pdf",
                        "file": {"url": "http://example.com/plan.pdf", "name": "plan.pdf"},
                    }
                ),
                Attachment.from_dict(
                    {"link": {"name": "Slides", "url": "http://example.com/slides"}}
                ),
            ],
        )
        client.get_posts.side_effect = [[post], []]

        downloaded, skipped, _ = await download_post_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 0
        client.download_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stops_paginating_at_cutoff(self, tmp_path):
        """Stops fetching pages when oldest post is before cutoff."""
        client = _make_mock_client()
        old_post = self._make_post(
            id=1, title="Old", timestamp_str="2025-06-01T10:00:00", attachments=[]
        )
        client.get_posts.side_effect = [
            [old_post],
            [],  # should not be reached due to cutoff
        ]

        downloaded, skipped, _ = await download_post_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 0
        assert client.get_posts.call_count == 1

    @pytest.mark.asyncio
    async def test_skips_posts_without_attachments(self, tmp_path):
        """Posts without attachments are skipped."""
        client = _make_mock_client()
        post = self._make_post(
            id=10, title="No Photos", timestamp_str="2026-03-01T10:00:00+01:00", attachments=[]
        )
        client.get_posts.side_effect = [[post], []]

        downloaded, skipped, _ = await download_post_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 0
        client.download_file.assert_not_awaited()


class TestDownloadMessageImages:
    """Tests for download_message_images."""

    @pytest.mark.asyncio
    async def test_deduplicates_threads(self, tmp_path):
        """Duplicate thread IDs from search results are deduplicated."""
        client = _make_mock_client()
        # Two search results for the same thread
        client.search_messages.return_value = [
            Message(
                id="m1",
                content_html="",
                _raw={
                    "thread": {"id": "t1", "subject": "Thread 1"},
                    "searchMessage": {"sendDateTime": "2026-03-01T10:00:00"},
                },
            ),
            Message(
                id="m2",
                content_html="",
                _raw={
                    "thread": {"id": "t1", "subject": "Thread 1"},
                    "searchMessage": {"sendDateTime": "2026-03-01T11:00:00"},
                },
            ),
        ]
        client.get_all_messages_for_thread.return_value = []

        await download_message_images(client, [100], ["INST1"], tmp_path, date(2026, 1, 1))

        # Should only fetch messages for thread once
        client.get_all_messages_for_thread.assert_awaited_once_with("t1")

    @pytest.mark.asyncio
    async def test_filters_messages_by_cutoff(self, tmp_path):
        """Messages before cutoff date are not downloaded."""
        client = _make_mock_client()
        client.search_messages.return_value = [
            Message(
                id="m1",
                content_html="",
                _raw={
                    "thread": {"id": "t1", "subject": "Thread"},
                    "searchMessage": {"sendDateTime": "2026-03-01T10:00:00"},
                },
            ),
        ]
        client.get_all_messages_for_thread.return_value = [
            {
                "sendDateTime": "2025-06-01T10:00:00",
                "hasAttachments": True,
                "attachments": [{"file": {"url": "http://example.com/old.jpg", "name": "old.jpg"}}],
            },
        ]

        downloaded, skipped, _ = await download_message_images(
            client, [100], ["INST1"], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 0
        client.download_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_downloads_attachments(self, tmp_path):
        """Downloads message attachments with correct paths."""
        client = _make_mock_client()
        client.search_messages.return_value = [
            Message(
                id="m1",
                content_html="",
                _raw={
                    "thread": {"id": "t1", "subject": "Photos"},
                    "searchMessage": {"sendDateTime": "2026-03-01T10:00:00"},
                },
            ),
        ]
        client.get_all_messages_for_thread.return_value = [
            {
                "sendDateTime": "2026-03-01T10:00:00",
                "hasAttachments": True,
                "attachments": [{"file": {"url": "http://example.com/img.jpg", "name": "img.jpg"}}],
            },
        ]

        downloaded, skipped, _ = await download_message_images(
            client, [100], ["INST1"], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 1
        assert (tmp_path / "messages" / "20260301 Photos" / "img.jpg").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["gallery", "posts", "messages"])
async def test_archive_keeps_collisions_and_reruns_by_identity(source, tmp_path):
    client = _make_mock_client()
    client.download_file.side_effect = lambda url, **_: url.split("?")[0].encode()
    records = []
    for identifier in (1, 2):
        records.append(
            {
                "id": identifier,
                "file": {
                    "id": identifier,
                    "name": "same.jpg",
                    "url": f"https://example.test/{identifier}?signature=old",
                },
            }
        )

    async def run():
        if source == "gallery":
            client.get_gallery_albums.return_value = [
                {
                    "id": i,
                    "title": "Same/title" if i == 1 else "Same:title",
                    "creationDate": "2026-03-01",
                }
                for i in (1, 2)
            ]
            client.get_album_pictures.side_effect = lambda ids, album_id: [
                record for record in records if record["id"] == album_id
            ]
            return await download_gallery_images(client, [100], tmp_path, date(2026, 1, 1))
        if source == "posts":
            posts = [
                MagicMock(
                    id=i,
                    title="Same/title" if i == 1 else "Same:title",
                    timestamp=datetime(2026, 3, 1),
                    attachments=[Attachment.from_dict({"id": i, "media": record})],
                )
                for record in records
                for i in [record["id"]]
            ]
            client.get_posts.side_effect = [posts, []]
            return await download_post_images(client, [100], tmp_path, date(2026, 1, 1))
        client.search_messages.return_value = [
            Message(
                id="search",
                content_html="",
                _raw={
                    "thread": {"id": "thread", "subject": "Same"},
                    "searchMessage": {"sendDateTime": "2026-03-01"},
                },
            )
        ]
        client.get_all_messages_for_thread.return_value = [
            {"id": i, "sendDateTime": "2026-03-01", "hasAttachments": True, "attachments": [record]}
            for record in records
            for i in [record["id"]]
        ]
        return await download_message_images(client, [100], ["INST"], tmp_path, date(2026, 1, 1))

    assert await run() == (2, 0, 0)
    files = list(tmp_path.rglob("*.jpg"))
    assert len(files) == 2
    assert {file.read_bytes() for file in files} == {
        b"https://example.test/1",
        b"https://example.test/2",
    }
    records.reverse()
    for record in records:
        record["file"]["url"] = record["file"]["url"].replace("old", "new")
    client.download_file.reset_mock()
    assert await run() == (0, 2, 0)
    client.download_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_export_reports_incomplete_search_without_changing_tuple(tmp_path):
    client = _make_mock_client()
    client.search_messages_result.side_effect = None
    client.search_messages_result.return_value = PaginationResult([], False, "no_progress")
    issues = []
    progress = []
    result = await download_message_images(
        client,
        [100],
        ["INST"],
        tmp_path,
        date(2026, 1, 1),
        on_progress=progress.append,
        on_incomplete=issues.append,
    )
    assert result == (0, 0, 0)
    assert issues == ["search:no_progress"]
    assert any("Incomplete message export" in line for line in progress)


@pytest.mark.asyncio
async def test_message_export_reports_incomplete_thread_read(tmp_path):
    client = _make_mock_client()
    client.search_messages.return_value = [
        Message(id="m", content_html="", _raw={"thread": {"id": "t", "subject": "Example"}})
    ]
    client.get_all_messages_for_thread_result.side_effect = None
    client.get_all_messages_for_thread_result.return_value = PaginationResult(
        [], False, "max_pages"
    )
    issues = []
    assert await download_message_images(
        client, [100], ["INST"], tmp_path, date(2026, 1, 1), on_incomplete=issues.append
    ) == (0, 0, 0)
    assert issues == ["thread:t:max_pages"]


def _one_picture(client):
    client.get_gallery_albums.return_value = [
        {"id": 1, "title": "Trip", "creationDate": "2026-03-01T12:00:00"},
    ]
    client.get_album_pictures.return_value = [
        {"file": {"url": "http://example.com/pic.jpg", "name": "pic.jpg"}, "tags": []},
    ]


@pytest.mark.asyncio
async def test_download_passes_the_size_cap_to_the_client(tmp_path):
    client = _make_mock_client()
    _one_picture(client)

    await download_gallery_images(client, [100], tmp_path, date(2026, 1, 1), max_bytes=1234)

    client.download_file.assert_awaited_once_with("http://example.com/pic.jpg", max_bytes=1234)


@pytest.mark.asyncio
async def test_file_over_the_cap_is_not_written_and_counts_as_failed(tmp_path):
    client = _make_mock_client()
    _one_picture(client)
    client.download_file.side_effect = DownloadTooLargeError("too big", max_bytes=10)

    counts = await download_gallery_images(client, [100], tmp_path, date(2026, 1, 1), max_bytes=10)

    assert counts == (0, 0, 1)
    assert not list(tmp_path.rglob("pic.jpg"))
    assert not (tmp_path / ".aula-archive.json").exists()


@pytest.mark.asyncio
async def test_download_that_raises_counts_as_failed(tmp_path):
    client = _make_mock_client()
    _one_picture(client)
    client.download_file.side_effect = RuntimeError("boom")

    counts = await download_gallery_images(client, [100], tmp_path, date(2026, 1, 1))

    assert counts == (0, 0, 1)


@pytest.mark.asyncio
async def test_failed_posts_page_counts_as_failed(tmp_path):
    client = _make_mock_client()
    client.get_posts.side_effect = RuntimeError("API down")

    counts = await download_post_images(client, [100], tmp_path, date(2026, 1, 1))

    assert counts == (0, 0, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
async def test_corrupt_manifest_is_moved_aside_and_replaced(content, tmp_path):
    (tmp_path / ".aula-archive.json").write_text(content)
    client = _make_mock_client()
    _one_picture(client)

    counts = await download_gallery_images(client, [100], tmp_path, date(2026, 1, 1))

    assert counts == (1, 0, 0)
    assert (tmp_path / ".aula-archive.json.corrupt").read_text() == content
    assert isinstance(json.loads((tmp_path / ".aula-archive.json").read_text()), dict)
