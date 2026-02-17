from dataclasses import dataclass, field

from ..utils.html import html_to_markdown, html_to_plain
from .base import AulaDataClass


@dataclass
class Message(AulaDataClass):
    id: str
    content_html: str
    _raw: dict | None = field(default=None, repr=False)

    @property
    def content(self) -> str:
        """Return the plain text content stripped from HTML."""
        return html_to_plain(self.content_html)

    @property
    def content_markdown(self) -> str:
        """Return the content converted to Markdown format."""
        return html_to_markdown(self.content_html)
