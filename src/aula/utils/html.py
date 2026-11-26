"""HTML content conversion utilities."""

import re

import html2text
from bs4 import BeautifulSoup

from .diagnostics import credential_logger

_LOGGER = credential_logger(__name__)

_BLOCK_TAGS = ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "tr")


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def strip_control_chars(text: str) -> str:
    """Remove C0 and C1 control characters except newline and tab."""
    return _CONTROL_CHARS.sub("", text)


def html_to_plain(html: str) -> str:
    """Convert HTML to plain text, stripping links, images, and tables."""
    if not html:
        return ""
    try:
        h = html2text.HTML2Text()
        h.unicode_snob = True
        h.images_to_alt = True
        h.single_line_break = True
        h.ignore_emphasis = True
        h.ignore_links = True
        h.ignore_images = True
        h.ignore_tables = True
        return strip_control_chars(h.handle(html)).strip()
    except (ValueError, AttributeError, UnicodeError) as e:
        _LOGGER.warning("Error converting HTML to plain text: %s", e)
        return strip_control_chars(html)


def html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown format."""
    if not html:
        return ""
    try:
        h = html2text.HTML2Text()
        h.unicode_snob = True
        return strip_control_chars(h.handle(html)).strip()
    except (ValueError, AttributeError, UnicodeError) as e:
        _LOGGER.warning("Error converting HTML to Markdown: %s", e)
        return strip_control_chars(html)


def _normalize_block(text: str) -> str:
    """Collapse runs of whitespace per line while keeping explicit line breaks."""
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def html_to_blocks(html: str) -> list[str]:
    """Convert HTML into text blocks, one per paragraph, heading or list item.

    Blocks are normalized and empty ones dropped, so joining them with a blank
    line restores the paragraph spacing that :func:`html_to_plain` collapses.
    List items get a bullet prefix.
    """
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:  # noqa: BLE001 - parser failures must not break rendering
        _LOGGER.warning("Error splitting HTML into blocks: %s", e)
        return [line for line in html_to_plain(html).splitlines() if line.strip()]

    for line_break in soup.find_all("br"):
        line_break.replace_with("\n")

    elements = soup.find_all(_BLOCK_TAGS)
    if not elements:
        text = _normalize_block(strip_control_chars(soup.get_text()))
        return [text] if text else []

    blocks = []
    for element in elements:
        if element.find(_BLOCK_TAGS):
            # A container; its descendants contribute the text instead.
            continue
        text = _normalize_block(strip_control_chars(element.get_text()))
        if not text:
            continue
        if element.name == "li" and not text.startswith(("-", "*", "•")):
            text = f"- {text}"
        blocks.append(text)
    return blocks
