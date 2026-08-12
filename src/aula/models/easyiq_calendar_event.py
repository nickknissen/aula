import datetime
import html
from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass

#: EasyIQ tags every calendar row with an ``itemType``. Its own widget source
#: (``/ts/Model/AulaHuskeliste/CalendarItem.js``) names them: 1 OpgaveFraForløb,
#: 2 LektieFraForløb, 3 Event, 4 Lektie, 5 Plan, 6 Holiday, 7 TimeTableEvent,
#: 8 VigtigInformation, 9 Ugeplan, 10 ClassroomStart, 11 ArbejdeFraForløb.
#:
#: The homework widget displays 1, 2, 3, 4 and 8, so homework set as part of a
#: course counts too, not only a bare ``Lektie``. The weekly plan pair is
#: empirical rather than read from source, confirmed against a live EasyIQ
#: account; the two overlap on 8 because both views show important notices.
WEEKPLAN_ITEM_TYPES = (8, 9)
HOMEWORK_ITEM_TYPES = (1, 2, 3, 4, 8)

#: Keys are matched case-insensitively: EasyIQ's calendar controller answers in
#: camelCase (``itemType``) and its homework controller in PascalCase
#: (``ItemType``), so a case-sensitive lookup silently parses nothing. The
#: ``*Display`` and ``*ISO`` variants come first because they are the ones the
#: widget itself reads.
_START_KEYS = ("starttimeiso", "start", "startdatetime", "starttime", "from")
_END_KEYS = ("endtimeiso", "end", "enddatetime", "endtime", "to")
_COURSE_KEYS = ("coursesdisplay", "courses", "course", "subject", "title", "name")
_ACTIVITY_KEYS = ("activitiesdisplay", "activities", "activity", "lesson", "classname")
_DESCRIPTION_KEYS = ("description", "details", "note", "content")
_ITEM_TYPE_KEYS = ("itemtype", "itemtypeid", "type")
_ID_KEYS = ("id", "workid")


def _fold_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Index a row by lowercased key so either casing resolves."""
    return {str(key).lower(): value for key, value in data.items()}


def _first_text(folded: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Return the first non-empty string value among ``keys``.

    Values are unescaped: the portal sends HTML entities in its text fields
    (``l&aelig;st``), unlike every other Aula source. A field holding only
    whitespace counts as empty, since the portal pads unused titles with a
    single space.
    """
    for key in keys:
        value = folded.get(key)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        if value is None or isinstance(value, bool):
            continue
        text = html.unescape(str(value)).strip()
        if text:
            return text
    return ""


#: EasyIQ's display timestamps, used when the ``*ISO`` field is absent.
_TIMESTAMP_FORMATS = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M")


def _first_timestamp(folded: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Return the first timestamp among ``keys``, normalised to ISO 8601.

    A row can carry ``StartTimeISO`` but leave ``EndTimeISO`` null, so the
    start and end of one event would otherwise come back in two different
    formats. Anything unrecognised is passed through untouched rather than
    dropped, since a value we cannot parse is still better than nothing.
    """
    text = _first_text(folded, keys)
    if not text:
        return ""
    try:
        return datetime.datetime.fromisoformat(text).isoformat()
    except ValueError:
        pass
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return text


def _item_type(folded: dict[str, Any]) -> int | None:
    """Return the EasyIQ item type as an int, tolerating string encodings."""
    for key in _ITEM_TYPE_KEYS:
        value = folded.get(key)
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
    event_id: str = ""
    start: str = ""
    end: str = ""
    courses: str = ""
    activities: str = ""
    description: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EasyIQCalendarEvent:
        folded = _fold_keys(data)
        return cls(
            _raw=data,
            item_type=_item_type(folded),
            event_id=_first_text(folded, _ID_KEYS),
            start=_first_timestamp(folded, _START_KEYS),
            end=_first_timestamp(folded, _END_KEYS),
            courses=_first_text(folded, _COURSE_KEYS),
            activities=_first_text(folded, _ACTIVITY_KEYS),
            description=_first_text(folded, _DESCRIPTION_KEYS),
        )

    @property
    def title(self) -> str:
        """Best available label for the row, preferring the subject.

        Empty when the row carries neither, so callers render their own
        placeholder rather than receiving one as data.
        """
        return self.courses or self.activities
