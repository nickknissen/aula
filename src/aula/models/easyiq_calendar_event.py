from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass

#: EasyIQ tags every calendar row with an ``itemType``. Lessons and regular
#: calendar entries make up the weekly plan; homework is its own type.
WEEKPLAN_ITEM_TYPES = (8, 9)
HOMEWORK_ITEM_TYPES = (4,)

_START_KEYS = ("start", "startDateTime", "startTime", "from")
_END_KEYS = ("end", "endDateTime", "endTime", "to")
_COURSE_KEYS = ("courses", "course", "subject", "title", "name")
_ACTIVITY_KEYS = ("activities", "activity", "lesson", "className")
_DESCRIPTION_KEYS = ("description", "details", "note", "content")
_ITEM_TYPE_KEYS = ("itemType", "itemTypeId", "type")


def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Return the first non-empty string value among ``keys``."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _item_type(data: dict[str, Any]) -> int | None:
    """Return the EasyIQ item type as an int, tolerating string encodings."""
    for key in _ITEM_TYPE_KEYS:
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("id", value.get("value"))
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except ValueError:
            continue
    return None


@dataclass
class EasyIQCalendarEvent(AulaDataClass):
    """One row from EasyIQ's ``CalendarGetWeekplanEvents`` endpoint.

    A single request returns the whole week for a child: lessons, calendar
    entries and homework interleaved, told apart by ``item_type``.
    """

    item_type: int | None = None
    start: str = ""
    end: str = ""
    courses: str = ""
    activities: str = ""
    description: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EasyIQCalendarEvent:
        return cls(
            _raw=data,
            item_type=_item_type(data),
            start=_first_text(data, _START_KEYS),
            end=_first_text(data, _END_KEYS),
            courses=_first_text(data, _COURSE_KEYS),
            activities=_first_text(data, _ACTIVITY_KEYS),
            description=_first_text(data, _DESCRIPTION_KEYS),
        )

    @property
    def title(self) -> str:
        """Best available label for the row, preferring the subject."""
        return self.courses or self.activities or "(untitled)"
