from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass
from .easyiq_calendar_event import EasyIQCalendarEvent


@dataclass
class EasyIQHomework(AulaDataClass):
    id: str
    title: str
    description: str = ""
    due_date: str = ""
    subject: str = ""
    #: EasyIQ's ``ActivitiesDisplay``, which on homework rows holds the class
    #: or team the assignment was set for, e.g. "6A" or "7-9F".
    activities: str = ""
    is_completed: bool = False
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EasyIQHomework:
        return cls(
            _raw=data,
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            due_date=data.get("dueDate", ""),
            subject=data.get("subject", ""),
            is_completed=data.get("isCompleted", False),
        )

    @classmethod
    def from_calendar_event(cls, event: EasyIQCalendarEvent) -> EasyIQHomework:
        """Build homework from an EasyIQ homework row.

        The portal carries no completion flag, so ``is_completed`` stays
        ``False``. The subject doubles as the title, matching how the EasyIQ
        widget itself labels homework.
        """
        return cls(
            _raw=event._raw,
            id=event.event_id or event.start,
            title=event.title,
            description=event.description,
            due_date=event.start,
            subject=event.courses,
            activities=event.activities,
            is_completed=False,
        )
