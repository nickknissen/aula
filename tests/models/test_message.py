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


def test_message_from_dict():
    data = {
        "id": "m1",
        "text": {"html": "<p>Hello</p>"},
        "attachments": [
            {
                "id": 5002,
                "status": "AVAILABLE",
                "file": {
                    "name": "weekplan.pdf",
                    "url": "https://files.example.test/weekplan.pdf",
                },
            }
        ],
    }
    msg = Message.from_dict(data)
    assert msg.id == "m1"
    assert msg.content_html == "<p>Hello</p>"
    assert msg.has_attachments is True
    assert len(msg.attachments) == 1
    assert msg.attachments[0].name == "weekplan.pdf"
    assert msg.attachments[0].url == "https://files.example.test/weekplan.pdf"
    assert msg._raw is data


def test_message_from_dict_plain_text_body():
    """Older messages carry their body as a bare string instead of a wrapper."""
    msg = Message.from_dict({"id": "m2", "text": "Hello"})
    assert msg.content_html == "Hello"


def test_message_from_dict_without_attachments():
    msg = Message.from_dict({"id": "m3", "text": {"html": ""}})
    assert msg.attachments == []
    assert msg.has_attachments is False
