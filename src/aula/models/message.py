from dataclasses import dataclass, field
from typing import Any

from ..utils.html import html_to_markdown, html_to_plain
from ..utils.mapping import get_in
from .attachment import Attachment, parse_attachments
from .base import AulaDataClass


@dataclass
class Message(AulaDataClass):
    id: str
    content_html: str
    attachments: list[Attachment] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @property
    def content(self) -> str:
        """Return the plain text content stripped from HTML."""
        return html_to_plain(self.content_html)

    @property
    def content_markdown(self) -> str:
        """Return the content converted to Markdown format."""
        return html_to_markdown(self.content_html)

    @property
    def has_attachments(self) -> bool:
        """Whether the message has anything attached to it."""
        return bool(self.attachments)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Create a Message instance from API response data."""
        message_id = data.get("id")
        # A body arrives wrapped as {"text": {"html": ...}} or, on older
        # messages, as a bare string. Anything else has no body to read.
        text = get_in(data, "text.html", default="") or get_in(data, "text", default="")
        return cls(
            id=str(message_id) if message_id is not None else "",
            content_html=text if isinstance(text, str) else "",
            attachments=parse_attachments(data.get("attachments")),
            _raw=data,
        )
