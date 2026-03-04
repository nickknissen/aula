from dataclasses import dataclass, field
from html.parser import HTMLParser

from .base import AulaDataClass


def _strip_html(text: str) -> str:
    """Strip HTML tags and return plain text."""
    parts: list[str] = []
    parser = HTMLParser()
    parser.handle_data = parts.append
    parser.feed(text)
    return "".join(parts).strip()


@dataclass
class Notification(AulaDataClass):
    id: str
    title: str
    module: str | None = None
    event_type: str | None = None
    notification_type: str | None = None
    institution_code: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    related_child_name: str | None = None
    post_id: int | None = None
    album_id: int | None = None
    media_id: int | None = None
    institution_profile_id: int | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Notification":
        notification_id = data.get("id") or data.get("notificationId") or "unknown"
        event_type = data.get("notificationEventType")
        if event_type == "NewMessagePrivateInbox" and data.get("messageText"):
            plain = _strip_html(str(data["messageText"]))
            title = plain[:40] if plain else "Untitled"
        else:
            title = (
                data.get("title")
                or data.get("heading")
                or data.get("postTitle")
                or event_type
                or "Untitled"
            )
        module = data.get("module") or data.get("moduleName") or data.get("notificationArea")

        return cls(
            id=str(notification_id),
            title=str(title),
            module=str(module) if module is not None else None,
            event_type=(
                str(data.get("notificationEventType"))
                if data.get("notificationEventType") is not None
                else None
            ),
            notification_type=(
                str(data.get("notificationType"))
                if data.get("notificationType") is not None
                else None
            ),
            institution_code=(
                str(data.get("institutionCode"))
                if data.get("institutionCode") is not None
                else None
            ),
            created_at=data.get("createdAt") or data.get("creationDate") or data.get("triggered"),
            expires_at=data.get("expires") or data.get("expiresAt"),
            related_child_name=(
                str(data.get("relatedChildName"))
                if data.get("relatedChildName") is not None
                else None
            ),
            post_id=data.get("postId") if isinstance(data.get("postId"), int) else None,
            album_id=data.get("albumId") if isinstance(data.get("albumId"), int) else None,
            media_id=data.get("mediaId") if isinstance(data.get("mediaId"), int) else None,
            institution_profile_id=(
                data.get("institutionProfileId")
                if isinstance(data.get("institutionProfileId"), int)
                else None
            ),
            _raw=data,
        )
