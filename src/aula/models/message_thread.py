from dataclasses import dataclass, field
from typing import Any

from ..const import WEB_PORTAL_URL
from .base import AulaDataClass


@dataclass
class MessageThread(AulaDataClass):
    thread_id: str
    subject: str
    _raw: dict | None = field(default=None, repr=False)
    #: Opens only in a browser logged in to Aula. A phone opens it in the browser, not the app.
    web_url: str | None = field(init=False)

    def __post_init__(self) -> None:
        self.web_url = f"{WEB_PORTAL_URL}/beskeder/{self.thread_id}" if self.thread_id else None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageThread:
        return cls(
            _raw=data,
            thread_id=data.get("id", ""),
            subject=data.get("subject", ""),
        )
