from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class MessageFolder(AulaDataClass):
    id: int
    name: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MessageFolder":
        return cls(
            _raw=data,
            id=data["id"],
            name=data.get("name", ""),
        )
