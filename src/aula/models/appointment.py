from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class Appointment(AulaDataClass):
    appointment_id: str
    title: str
    start: str = ""
    end: str = ""
    description: str = ""
    item_type: int | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Appointment":
        return cls(
            _raw=data,
            appointment_id=data.get("appointmentId", ""),
            title=data.get("title", ""),
            start=data.get("start", ""),
            end=data.get("end", ""),
            description=data.get("description", ""),
            item_type=data.get("itemType"),
        )
