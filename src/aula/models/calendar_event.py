import dataclasses
import datetime
import itertools
from collections.abc import Iterable
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
    #: Every primary teacher on the lesson, in the order Aula listed them.
    #: ``teacher_name`` is the first of these, kept so existing callers and the
    #: JSON output keep working; read this when a lesson can have more than one
    #: adult attached, which is the common case in the younger years.
    teacher_names: list[str] = field(default_factory=list)
    #: Every substitute on the lesson, same relationship to ``substitute_name``.
    substitute_names: list[str] = field(default_factory=list)


def merge_duplicate_lessons(events: list[CalendarEvent]) -> list[CalendarEvent]:
    """Collapse the rows Aula returns once per adult into one event each.

    When two or more adults are attached to the same lesson, Aula's calendar
    answers with one ``lesson`` row per adult: identical ``title``,
    ``startDateTime``, ``endDateTime``, ``primaryResource`` and
    ``belongsToProfiles``, but a distinct ``id`` and a different teacher in
    ``participants``. Rendered as-is that shows the same lesson two or three
    times in a row, every day.

    Rows are merged only when the lesson they describe is indistinguishable --
    same title, timeslot, room and child. Two genuinely different events that
    merely overlap in time keep their own entries, so nothing real is hidden.

    The surviving event keeps the first row's ``id`` and ``_raw``; the adults
    from the rows folded into it are collected into ``teacher_names`` and
    ``substitute_names``. ``has_substitute`` is true when any row reported one.
    A new list of new events is returned; the inputs are left untouched.
    Group order follows each lesson's first appearance in ``events``.
    """

    def key(event: CalendarEvent) -> tuple:
        return (
            event.title,
            event.start_datetime,
            event.end_datetime,
            event.location,
            event.belongs_to,
        )

    groups: dict[tuple, list[CalendarEvent]] = {}
    for event in events:
        groups.setdefault(key(event), []).append(event)

    merged = []
    for group in groups.values():
        first = group[0]
        teachers = _unique(
            itertools.chain.from_iterable(e.teacher_names or [e.teacher_name] for e in group)
        )
        substitutes = _unique(
            itertools.chain.from_iterable(e.substitute_names or [e.substitute_name] for e in group)
        )
        merged.append(
            dataclasses.replace(
                first,
                # Keep the scalars pointing at the first adult so callers that
                # only know about them read a real name, not an arbitrary one.
                teacher_name=teachers[0] if teachers else first.teacher_name,
                substitute_name=substitutes[0] if substitutes else None,
                has_substitute=any(e.has_substitute for e in group),
                teacher_names=teachers,
                substitute_names=substitutes,
            )
        )

    return merged


def _unique(names: Iterable[str | None]) -> list[str]:
    """Return the non-empty names, de-duplicated, in first-seen order."""
    return list(dict.fromkeys(name for name in names if name))
