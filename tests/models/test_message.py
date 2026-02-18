"""Tests for aula.models.message."""

from aula.models.message import Message


def test_message_content():
    msg = Message(id="1", content_html="<p>Hello</p>")
    assert "Hello" in msg.content
    assert "<p>" not in msg.content


def test_message_content_empty():
    msg = Message(id="1", content_html="")
    assert msg.content == ""


def test_message_content_markdown():
    msg = Message(id="1", content_html='<a href="https://example.com">link</a>')
    assert "example.com" in msg.content_markdown


def test_message_content_markdown_empty():
    msg = Message(id="1", content_html="")
    assert msg.content_markdown == ""


def test_message_dict_conversion():
    msg = Message(id="42", content_html="<b>Bold</b>")
    result = dict(msg)
    assert result["id"] == "42"
    assert result["content_html"] == "<b>Bold</b>"
    assert "_raw" not in result


def test_message_raw_preserved():
    msg = Message(id="1", content_html="text", _raw={"original": True})
    assert msg._raw == {"original": True}
    assert "_raw" not in dict(msg)
