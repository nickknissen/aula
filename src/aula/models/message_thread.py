from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class MessageThread(AulaDataClass):
    thread_id: str
    subject: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageThread:
        return cls(
            _raw=data,
            thread_id=data.get("id", ""),
            subject=data.get("subject", ""),
        )
