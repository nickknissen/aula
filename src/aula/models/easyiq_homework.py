from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class EasyIQHomework(AulaDataClass):
    id: str
    title: str
    description: str = ""
    due_date: str = ""
    subject: str = ""
    is_completed: bool = False
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EasyIQHomework":
        return cls(
            _raw=data,
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            due_date=data.get("dueDate", ""),
            subject=data.get("subject", ""),
            is_completed=data.get("isCompleted", False),
        )
