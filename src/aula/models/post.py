import datetime
from dataclasses import dataclass, field
from typing import Any

from ..utils import html_to_markdown, html_to_plain
from .base import AulaDataClass
from .profile_reference import ProfileReference


@dataclass
class Post(AulaDataClass):
    """Represents a post in Aula (news, announcements, etc.)."""

    id: int
    title: str
    content_html: str
    timestamp: datetime.datetime | None
    owner: ProfileReference
    allow_comments: bool
    shared_with_groups: list[dict]
    publish_at: datetime.datetime | None
    is_published: bool
    expire_at: datetime.datetime | None
    is_expired: bool
    is_important: bool
    important_from: datetime.datetime | None
    important_to: datetime.datetime | None
    attachments: list[dict]
    comment_count: int
    can_current_user_delete: bool
    can_current_user_comment: bool
    edited_at: datetime.datetime | None = None
    _raw: dict | None = field(default=None, repr=False)

    @property
    def content(self) -> str:
        """Return the plain text content stripped from HTML."""
        return html_to_plain(self.content_html)

    @property
    def content_markdown(self) -> str:
        """Return the content converted to Markdown format."""
        return html_to_markdown(self.content_html)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Post":
        """Create a Post instance from API response data."""

        def parse_datetime(dt_str: str | None) -> datetime.datetime | None:
            if not dt_str:
                return None
            try:
                # Handle timezone offset
                if dt_str.endswith("Z"):
                    dt_str = dt_str[:-1] + "+00:00"
                return datetime.datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                return None

        owner = ProfileReference.from_dict(data.get("ownerProfile", {}))

        return cls(
            id=data["id"],
            title=data.get("title", ""),
            content_html=data.get("content", {}).get("html", ""),
            timestamp=parse_datetime(data.get("timestamp")),
            owner=owner,
            allow_comments=data.get("allowComments", False),
            shared_with_groups=data.get("sharedWithGroups", []),
            publish_at=parse_datetime(data.get("publishAt")),
            is_published=data.get("isPublished", False),
            expire_at=parse_datetime(data.get("expireAt")),
            is_expired=data.get("isExpired", False),
            is_important=data.get("isImportant", False),
            important_from=parse_datetime(data.get("importantFrom")),
            important_to=parse_datetime(data.get("importantTo")),
            attachments=data.get("attachments", []),
            comment_count=data.get("commentCount", 0),
            can_current_user_delete=data.get("canCurrentUserDelete", False),
            can_current_user_comment=data.get("canCurrentUserComment", False),
            edited_at=parse_datetime(data.get("editedAt")),
            _raw=data,
        )
