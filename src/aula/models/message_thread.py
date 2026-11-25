import datetime
from dataclasses import dataclass, field
from typing import Any

from ..const import WEB_PORTAL_URL
from ..utils.dates import parse_api_datetime
from ..utils.html import html_to_plain
from ..utils.mapping import get_in
from .base import AulaDataClass


@dataclass
class ThreadLatestMessage(AulaDataClass):
    """The newest message of a thread, as the thread list shows it."""

    id: str
    sent_at: datetime.datetime | None
    text: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThreadLatestMessage:
        message_id = data.get("id")
        html = get_in(data, "text.html", default="")
        return cls(
            _raw=data,
            id=str(message_id) if message_id is not None else "",
            sent_at=parse_api_datetime(data.get("sendDateTime")),
            text=html_to_plain(html) if isinstance(html, str) else "",
        )


@dataclass
class ThreadChild(AulaDataClass):
    """A child a thread is about."""

    #: Matches ``Child.profile_id``, not ``Child.id``.
    profile_id: int
    display_name: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThreadChild | None:
        profile_id = data.get("profileId")
        if not isinstance(profile_id, int) or isinstance(profile_id, bool):
            return None
        return cls(_raw=data, profile_id=profile_id, display_name=data.get("displayName") or "")


@dataclass
class ThreadRecipient(AulaDataClass):
    """Someone taking part in a thread."""

    full_name: str
    short_name: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThreadRecipient:
        return cls(
            _raw=data,
            full_name=data.get("fullName") or "",
            short_name=data.get("shortName") or "",
        )


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


@dataclass
class MessageThread(AulaDataClass):
    thread_id: str
    subject: str
    _raw: dict | None = field(default=None, repr=False)
    #: Opens only in a browser logged in to Aula. A phone opens it in the browser, not the app.
    web_url: str | None = field(init=False)
    #: When the newest message in the thread was sent.
    last_updated: datetime.datetime | None = field(default=None, kw_only=True)
    is_read: bool | None = field(default=None, kw_only=True)
    is_sensitive: bool = field(default=False, kw_only=True)
    latest_message: ThreadLatestMessage | None = field(default=None, kw_only=True)
    regarding_children: list[ThreadChild] = field(default_factory=list, kw_only=True)
    recipients: list[ThreadRecipient] = field(default_factory=list, kw_only=True)

    def __post_init__(self) -> None:
        self.web_url = f"{WEB_PORTAL_URL}/beskeder/{self.thread_id}" if self.thread_id else None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageThread:
        latest = data.get("latestMessage")
        latest_message = ThreadLatestMessage.from_dict(latest) if isinstance(latest, dict) else None
        return cls(
            _raw=data,
            thread_id=str(thread_id) if (thread_id := data.get("id")) is not None else "",
            subject=data.get("subject", ""),
            last_updated=latest_message.sent_at if latest_message else None,
            latest_message=latest_message,
            regarding_children=[
                child
                for item in _dicts(data.get("regardingChildren"))
                if (child := ThreadChild.from_dict(item)) is not None
            ],
            recipients=[ThreadRecipient.from_dict(item) for item in _dicts(data.get("recipients"))],
            is_read=read if isinstance(read := data.get("read"), bool) else None,
            is_sensitive=data.get("sensitive") is True,
        )
