"""Tests for aula.utils.html."""

from aula.utils.html import html_to_blocks, html_to_markdown, html_to_plain


def test_html_to_plain_strips_tags():
    result = html_to_plain("<p>Hello <b>world</b></p>")
    assert "Hello" in result
    assert "world" in result
    assert "<p>" not in result


def test_html_to_plain_empty_string():
    assert html_to_plain("") == ""


def test_html_to_plain_no_tags():
    result = html_to_plain("plain text")
    assert "plain text" in result


def test_html_to_markdown_preserves_links():
    result = html_to_markdown('<a href="https://example.com">link</a>')
    assert "example.com" in result
    assert "link" in result


def test_html_to_markdown_empty_string():
    assert html_to_markdown("") == ""


def test_html_to_plain_nested_tags():
    result = html_to_plain("<div><p><b>nested</b></p></div>")
    assert "nested" in result
    assert "<" not in result


class TestHtmlToBlocks:
    def test_empty_string(self):
        assert html_to_blocks("") == []

    def test_paragraphs_become_separate_blocks(self):
        blocks = html_to_blocks("<p>First</p><p>Second</p>")
        assert blocks == ["First", "Second"]

    def test_drops_spacer_paragraphs(self):
        blocks = html_to_blocks("<p>Text</p><p><br></p><p>&nbsp;</p><p>More</p>")
        assert blocks == ["Text", "More"]

    def test_nested_container_is_not_duplicated(self):
        assert html_to_blocks("<div><p>Only once</p></div>") == ["Only once"]

    def test_line_break_stays_inside_block(self):
        assert html_to_blocks("<p>One<br>Two</p>") == ["One\nTwo"]

    def test_list_items_get_bullets(self):
        blocks = html_to_blocks("<ul><li>A</li><li>- B</li></ul>")
        assert blocks == ["- A", "- B"]

    def test_collapses_whitespace_and_decodes_entities(self):
        assert html_to_blocks("<p>l&aelig;se   hjemme</p>") == ["læse hjemme"]

    def test_html_without_block_tags(self):
        assert html_to_blocks("just <b>text</b>") == ["just text"]
