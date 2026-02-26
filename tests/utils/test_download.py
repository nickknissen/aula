"""Tests for aula.utils.download."""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aula.models.message import Message
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

        downloaded, skipped = await download_gallery_images(
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

        downloaded, skipped = await download_gallery_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 0
        client.get_album_pictures.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_existing_files(self, tmp_path):
        """Existing files are counted as skipped."""
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

        downloaded, skipped = await download_gallery_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 0
        assert skipped == 1
        client.download_file.assert_not_awaited()

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

        downloaded, skipped = await download_gallery_images(
            client, [100], tmp_path, date(2026, 1, 1), tags=["child1"]
        )

        assert downloaded == 1

    @pytest.mark.asyncio
    async def test_handles_api_failure(self, tmp_path):
        """API failure for album list returns zero counts."""
        client = _make_mock_client()
        client.get_gallery_albums.side_effect = RuntimeError("API down")

        downloaded, skipped = await download_gallery_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 0
        assert skipped == 0


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
                {"media": {"file": {"url": "http://example.com/photo.jpg", "name": "photo.jpg"}}},
            ],
        )
        client.get_posts.side_effect = [[post], []]

        downloaded, skipped = await download_post_images(
            client, [100], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 1
        assert (tmp_path / "posts" / "20260301 School Trip" / "photo.jpg").exists()

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

        downloaded, skipped = await download_post_images(
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

        downloaded, skipped = await download_post_images(
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

        await download_message_images(
            client, [100], ["INST1"], tmp_path, date(2026, 1, 1)
        )

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
                "attachments": [
                    {"file": {"url": "http://example.com/old.jpg", "name": "old.jpg"}}
                ],
            },
        ]

        downloaded, skipped = await download_message_images(
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
                "attachments": [
                    {"file": {"url": "http://example.com/img.jpg", "name": "img.jpg"}}
                ],
            },
        ]

        downloaded, skipped = await download_message_images(
            client, [100], ["INST1"], tmp_path, date(2026, 1, 1)
        )

        assert downloaded == 1
        assert (tmp_path / "messages" / "20260301 Photos" / "img.jpg").exists()
