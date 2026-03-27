from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class NotificationSetting(AulaDataClass):
    module: str = ""
    is_enabled: bool = False
    push_enabled: bool = False
    email_enabled: bool = False
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotificationSetting":
        return cls(
            _raw=data,
            module=data.get("module", "") or data.get("notificationArea", ""),
            is_enabled=bool(data.get("isEnabled", False)),
            push_enabled=bool(data.get("pushEnabled", data.get("isPushEnabled", False))),
            email_enabled=bool(data.get("emailEnabled", data.get("isEmailEnabled", False))),
        )
