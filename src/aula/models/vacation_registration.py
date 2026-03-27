from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class VacationRegistration(AulaDataClass):
    id: int
    child_name: str = ""
    institution_profile_id: int = 0
    start_date: str | None = None
    end_date: str | None = None
    status: str = ""
    vacation_type: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VacationRegistration":
        return cls(
            _raw=data,
            id=data.get("id", 0),
            child_name=data.get("childName", "") or data.get("name", ""),
            institution_profile_id=data.get("institutionProfileId", 0),
            start_date=data.get("startDate") or data.get("fromDate"),
            end_date=data.get("endDate") or data.get("toDate"),
            status=data.get("status", ""),
            vacation_type=data.get("vacationType", "") or data.get("type", ""),
        )
