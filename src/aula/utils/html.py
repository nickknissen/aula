"""HTML content conversion utilities."""

import logging

import html2text

_LOGGER = logging.getLogger(__name__)


def html_to_plain(html: str) -> str:
    """Convert HTML to plain text, stripping links, images, and tables."""
    if not html:
        return ""
    try:
        h = html2text.HTML2Text()
        h.images_to_alt = True
        h.single_line_break = True
        h.ignore_emphasis = True
        h.ignore_links = True
        h.ignore_images = True
        h.ignore_tables = True
        return h.handle(html).strip()
    except Exception as e:
        _LOGGER.warning("Error converting HTML to plain text: %s", e)
        return html


def html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown format."""
    if not html:
        return ""
    try:
        h = html2text.HTML2Text()
        return h.handle(html).strip()
    except Exception as e:
        _LOGGER.warning("Error converting HTML to Markdown: %s", e)
        return html
