"""Tests for aula.models.post."""

from aula.models.post import Post


def test_post_from_dict():
    data = {
        "id": 1,
        "title": "Announcement",
        "content": {"html": "<p>Hello world</p>"},
        "timestamp": "2025-01-15T10:00:00Z",
        "ownerProfile": {
            "id": 1,
            "profileId": 10,
            "firstName": "John",
            "lastName": "Doe",
            "fullName": "John Doe",
            "shortName": "JD",
            "role": "teacher",
            "institution": {"institutionName": "School"},
        },
        "allowComments": True,
        "sharedWithGroups": [{"id": 1}],
        "publishAt": "2025-01-15T09:00:00+01:00",
        "isPublished": True,
        "expireAt": None,
        "isExpired": False,
        "isImportant": True,
        "importantFrom": "2025-01-15T00:00:00Z",
        "importantTo": "2025-01-20T00:00:00Z",
        "attachments": [],
        "commentCount": 5,
        "canCurrentUserDelete": False,
        "canCurrentUserComment": True,
        "editedAt": "2025-01-15T11:00:00Z",
    }
    post = Post.from_dict(data)
    assert post.id == 1
    assert post.title == "Announcement"
    assert post.content_html == "<p>Hello world</p>"
    assert post.timestamp is not None
    assert post.timestamp.year == 2025
    assert post.owner.full_name == "John Doe"
    assert post.allow_comments is True
    assert post.is_published is True
    assert post.is_important is True
    assert post.comment_count == 5
    assert post.edited_at is not None
    assert post._raw is data


def test_post_from_dict_minimal():
    data = {
        "id": 2,
        "ownerProfile": {
            "id": 1,
            "profileId": 1,
        },
    }
    post = Post.from_dict(data)
    assert post.id == 2
    assert post.title == ""
    assert post.content_html == ""
    assert post.timestamp is None
    assert post.is_published is False
    assert post.attachments == []
    assert post.edited_at is None


def test_post_content_property():
    data = {
        "id": 1,
        "content": {"html": "<p>Some <b>bold</b> text</p>"},
        "ownerProfile": {"id": 1, "profileId": 1},
    }
    post = Post.from_dict(data)
    assert "bold" in post.content
    assert "<b>" not in post.content


def test_post_content_markdown_property():
    data = {
        "id": 1,
        "content": {"html": '<a href="https://example.com">link</a>'},
        "ownerProfile": {"id": 1, "profileId": 1},
    }
    post = Post.from_dict(data)
    assert "example.com" in post.content_markdown


def test_post_datetime_parsing_invalid():
    data = {
        "id": 1,
        "timestamp": "not-a-date",
        "ownerProfile": {"id": 1, "profileId": 1},
    }
    post = Post.from_dict(data)
    assert post.timestamp is None


def test_post_dict_conversion():
    data = {
        "id": 1,
        "title": "Test",
        "content": {"html": ""},
        "ownerProfile": {
            "id": 1,
            "profileId": 1,
        },
    }
    post = Post.from_dict(data)
    result = dict(post)
    assert result["title"] == "Test"
    assert "_raw" not in result
