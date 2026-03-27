from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class AutoReply(AulaDataClass):
    is_enabled: bool = False
    message: str = ""
    start_date: str | None = None
    end_date: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutoReply":
        return cls(
            _raw=data,
            is_enabled=bool(data.get("isAutoReplyOn") or data.get("isEnabled", False)),
            message=data.get("autoReplyMessage", "") or data.get("message", ""),
            start_date=data.get("startDate") or data.get("fromDate"),
            end_date=data.get("endDate") or data.get("toDate"),
        )
