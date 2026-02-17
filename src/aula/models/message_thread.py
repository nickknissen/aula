from dataclasses import dataclass, field

from .base import AulaDataClass


@dataclass
class MessageThread(AulaDataClass):
    thread_id: str
    subject: str
    _raw: dict | None = field(default=None, repr=False)
