from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


def _strict_bool(value: Any) -> bool:
    """Parse only the Boolean encodings emitted by Aula and EasyIQ."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return isinstance(value, str) and value.strip().casefold() in {"true", "1", "yes"}


@dataclass
class Appointment(AulaDataClass):
    appointment_id: str
    title: str
    start: str = ""
    end: str = ""
    description: str = ""
    #: EasyIQ's ``ActivitiesDisplay``: the class or team the lesson belongs
    #: to, e.g. "6A". Empty for sources that do not carry one.
    activities: str = ""
    item_type: int | None = None
    _raw: dict | None = field(default=None, repr=False)
    owner_name: str = field(default="", kw_only=True)
    is_all_day: bool = field(default=False, kw_only=True)
    is_notice: bool = field(default=False, kw_only=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Appointment:
        return cls(
            _raw=data,
            appointment_id=data.get("appointmentId", ""),
            title=data.get("title", ""),
            start=data.get("start", ""),
            end=data.get("end", ""),
            description=data.get("description", ""),
            item_type=data.get("itemType"),
            owner_name=data.get("ownerName", data.get("owner_name", "")),
            is_all_day=_strict_bool(data.get("isAllDay", data.get("is_all_day"))),
            is_notice=_strict_bool(data.get("isNotice", data.get("is_notice"))),
        )
