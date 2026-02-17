import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .base import AulaDataClass


def _parse_dotnet_date(value: str | None) -> datetime | None:
    """Parse a .NET JSON date string like '/Date(1771196400000-0000)/'."""
    if not value:
        return None
    match = re.search(r"/Date\((\d+)([+-]\d{4})?\)/", value)
    if not match:
        return None
    return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc)


@dataclass
class MUTaskClass(AulaDataClass):
    id: int
    name: str
    subject_id: int
    subject_name: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MUTaskClass":
        return cls(
            _raw=data,
            id=data.get("id", 0),
            name=data.get("navn", ""),
            subject_id=data.get("fagId", 0),
            subject_name=data.get("fagNavn", ""),
        )


@dataclass
class MUTaskCourse(AulaDataClass):
    id: str
    name: str
    icon: str
    yearly_plan_id: str
    color: str | None
    url: str | None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MUTaskCourse":
        return cls(
            _raw=data,
            id=data.get("id", ""),
            name=data.get("navn", ""),
            icon=data.get("ikon", ""),
            yearly_plan_id=data.get("aarsplanId", ""),
            color=data.get("farve"),
            url=data.get("url"),
        )


@dataclass
class MUTask(AulaDataClass):
    id: str
    title: str
    task_type: str
    due_date: datetime | None
    weekday: str
    week_number: int
    is_completed: bool
    student_name: str
    unilogin: str
    url: str
    classes: list[MUTaskClass] = field(default_factory=list)
    course: MUTaskCourse | None = None
    student_count: int | None = None
    completed_count: int | None = None
    placement: str | None = None
    placement_time: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MUTask":
        classes = [MUTaskClass.from_dict(h) for h in data.get("hold", [])]
        forloeb = data.get("forloeb")
        return cls(
            _raw=data,
            id=data["id"],
            title=data.get("title", ""),
            task_type=data.get("opgaveType", ""),
            due_date=_parse_dotnet_date(data.get("afleveringsdato")),
            weekday=data.get("ugedag", ""),
            week_number=data.get("ugenummer", 0),
            is_completed=data.get("erFaerdig", False),
            student_name=data.get("kuvertnavn", ""),
            unilogin=data.get("unilogin", ""),
            url=data.get("url", ""),
            classes=classes,
            course=MUTaskCourse.from_dict(forloeb) if forloeb else None,
            student_count=data.get("antalElever"),
            completed_count=data.get("antalFaerdige"),
            placement=data.get("placering"),
            placement_time=data.get("placeringTidspunkt"),
        )
