from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass
from .institution_profile import InstitutionProfile


@dataclass
class SpareTimeActivity(AulaDataClass):
    start_time: str | None = None
    end_time: str | None = None
    comment: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpareTimeActivity":
        return cls(
            _raw=data,
            start_time=data.get("startTime"),
            end_time=data.get("endTime"),
            comment=data.get("comment"),
        )


@dataclass
class DayTemplate(AulaDataClass):
    id: int | None = None
    day_of_week: int | None = None
    by_date: str | None = None
    repeat_pattern: str | None = None
    repeat_from_date: str | None = None
    repeat_to_date: str | None = None
    is_on_vacation: bool = False
    activity_type: int | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    exit_with: str | None = None
    comment: str | None = None
    spare_time_activity: SpareTimeActivity | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DayTemplate":
        sta_data = data.get("spareTimeActivity")
        return cls(
            _raw=data,
            id=data.get("id"),
            day_of_week=data.get("dayOfWeek"),
            by_date=data.get("byDate"),
            repeat_pattern=data.get("repeatPattern"),
            repeat_from_date=data.get("repeatFromDate"),
            repeat_to_date=data.get("repeatToDate"),
            is_on_vacation=data.get("isOnVacation", False),
            activity_type=data.get("activityType"),
            entry_time=data.get("entryTime"),
            exit_time=data.get("exitTime"),
            exit_with=data.get("exitWith"),
            comment=data.get("comment"),
            spare_time_activity=SpareTimeActivity.from_dict(sta_data) if sta_data else None,
        )


@dataclass
class PresenceWeekTemplate(AulaDataClass):
    institution_profile: InstitutionProfile | None = None
    day_templates: list[DayTemplate] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceWeekTemplate":
        ip_data = data.get("institutionProfile")
        return cls(
            _raw=data,
            institution_profile=InstitutionProfile.from_dict(ip_data) if ip_data else None,
            day_templates=[
                DayTemplate.from_dict(d) for d in data.get("dayTemplates", [])
            ],
        )
