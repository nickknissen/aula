import datetime
import re
from dataclasses import dataclass, field
from typing import Any

from ..utils.dates import parse_api_datetime
from .base import AulaDataClass


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


def _parse_utc(value: Any) -> datetime.datetime | None:
    """Docendo sends UTC, sometimes without an offset, so naive values are UTC."""
    parsed = parse_api_datetime(value)
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed


def _normalize_class_name(name: str | None) -> str:
    return re.sub(r"[\W_]", "", name or "").lower()


@dataclass
class DocendoLesson(AulaDataClass):
    title: str
    start_time: datetime.datetime | None
    end_time: datetime.datetime | None
    description: str
    learning_goal: str
    notes_for_students: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocendoLesson:
        return cls(
            _raw=data,
            title=_text(data, "title"),
            start_time=_parse_utc(data.get("startTime")),
            end_time=_parse_utc(data.get("endTime")),
            description=_text(data, "description"),
            learning_goal=_text(data, "learningGoal"),
            notes_for_students=_text(data, "notesForStudents"),
        )

    @property
    def has_content(self) -> bool:
        """Docendo also lists breaks and empty lessons, which carry no plan text."""
        return bool(self.description or self.learning_goal or self.notes_for_students)


@dataclass
class DocendoWeekPlan(AulaDataClass):
    """One class's weekplan. Docendo names it after the class, e.g. "4A"."""

    name: str
    note: str
    lessons: list[DocendoLesson] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocendoWeekPlan:
        events = data.get("events")
        lessons = [
            DocendoLesson.from_dict(event)
            for event in (events if isinstance(events, list) else [])
            if isinstance(event, dict)
        ]
        lessons.sort(
            key=lambda lesson: (
                lesson.start_time or datetime.datetime.max.replace(tzinfo=datetime.UTC)
            )
        )
        return cls(_raw=data, name=_text(data, "name"), note=_text(data, "note"), lessons=lessons)

    def matches_class(self, class_name: str | None) -> bool:
        """Compare against a child's class, ignoring case, spaces and punctuation.

        Aula exposes the class as ``institutionProfile.metadata``, and "4.A" or
        "4 a" there should match a plan named "4A".
        """
        wanted = _normalize_class_name(class_name)
        return bool(wanted) and _normalize_class_name(self.name) == wanted
