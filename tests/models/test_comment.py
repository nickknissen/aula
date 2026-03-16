"""Tests for aula.models.comment."""

from aula.models.comment import Comment


def test_comment_from_dict():
    data = {
        "id": 1,
        "text": "<p>Hello <b>world</b></p>",
        "owner": {"name": "Alice", "institutionProfileId": 42},
        "createdAt": "2026-03-16T10:00:00",
    }
    comment = Comment.from_dict(data)
    assert comment.id == 1
    assert comment.content_html == "<p>Hello <b>world</b></p>"
    assert comment.creator_name == "Alice"
    assert comment.creator_institution_profile_id == 42
    assert comment.created_at == "2026-03-16T10:00:00"
    assert comment._raw is data


def test_comment_from_dict_missing_optional():
    data = {"id": 2, "text": "Simple"}
    comment = Comment.from_dict(data)
    assert comment.creator_name == ""
    assert comment.creator_institution_profile_id is None
    assert comment.created_at == ""


def test_comment_content_property():
    comment = Comment(id=1, content_html="<p>Hello <b>world</b></p>", creator_name="Test")
    assert "Hello" in comment.content
    assert "<p>" not in comment.content


def test_comment_dict_conversion():
    comment = Comment(id=1, content_html="text", creator_name="A")
    result = dict(comment)
    assert result["id"] == 1
    assert "_raw" not in result
