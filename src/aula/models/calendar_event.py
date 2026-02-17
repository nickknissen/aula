import datetime
from dataclasses import dataclass, field

from .base import AulaDataClass


@dataclass
class CalendarEvent(AulaDataClass):
    id: int
    title: str
    start_datetime: datetime.datetime
    end_datetime: datetime.datetime
    teacher_name: str | None
    has_substitute: bool
    substitute_name: str | None
    location: str | None
    belongs_to: int | None
    _raw: dict | None = field(default=None, repr=False)
