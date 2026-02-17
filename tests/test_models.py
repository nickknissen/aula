"""Tests for aula.models."""

from aula.models.child import Child
from aula.models.message import Message
from aula.models.profile import Profile


def test_child_from_dict():
    data = {
        "id": 1,
        "profileId": 100,
        "name": "Alice",
        "institutionProfile": {"institutionName": "School A"},
        "profilePicture": {"url": "https://example.com/pic.jpg"},
    }
    child = Child.from_dict(data)
    assert child.id == 1
    assert child.profile_id == 100
    assert child.name == "Alice"
    assert child.institution_name == "School A"
    assert child.profile_picture == "https://example.com/pic.jpg"
    assert child._raw is data


def test_child_from_dict_missing_optional():
    data = {"id": 2, "profileId": 200, "name": "Bob"}
    child = Child.from_dict(data)
    assert child.institution_name == ""
    assert child.profile_picture == ""


def test_child_dict_conversion():
    child = Child(id=1, profile_id=100, name="Test", institution_name="X", profile_picture="")
    result = dict(child)
    assert result["name"] == "Test"
    assert "_raw" not in result


def test_message_content():
    msg = Message(id="1", content_html="<p>Hello</p>")
    assert "Hello" in msg.content
    assert "<p>" not in msg.content


def test_message_content_markdown():
    msg = Message(id="1", content_html='<a href="https://example.com">link</a>')
    assert "example.com" in msg.content_markdown


def test_profile_creation():
    profile = Profile(
        profile_id=1,
        display_name="Test User",
        children=[],
        institution_profile_ids=[10, 20],
    )
    assert profile.display_name == "Test User"
    result = dict(profile)
    assert result["institution_profile_ids"] == [10, 20]
