"""Tests for aula.utils.html."""

from aula.utils.html import html_to_markdown, html_to_plain


def test_html_to_plain_strips_tags():
    result = html_to_plain("<p>Hello <b>world</b></p>")
    assert "Hello" in result
    assert "world" in result
    assert "<p>" not in result


def test_html_to_plain_empty_string():
    assert html_to_plain("") == ""


def test_html_to_plain_none_like():
    assert html_to_plain("") == ""


def test_html_to_markdown_preserves_links():
    result = html_to_markdown('<a href="https://example.com">link</a>')
    assert "example.com" in result
    assert "link" in result


def test_html_to_markdown_empty_string():
    assert html_to_markdown("") == ""
