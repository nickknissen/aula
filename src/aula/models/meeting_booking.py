"""Booked intervals for Aula's parent meetings."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..utils.diagnostics import credential_logger
from ..utils.mapping import get_in
from .base import AulaDataClass
from .calendar_event import CalendarEvent

_LOGGER = credential_logger(__name__)
MEETING_TYPES = frozenset({"school_home_meeting", "parental_meeting"})


@dataclass
class MeetingBooking(AulaDataClass):
    meeting_id: int
    child_id: int
    title: str
    meeting_type: str
    start_datetime: datetime
    end_datetime: datetime
    location: str | None = None
    _raw: dict[str, Any] | None = field(default=None, repr=False)

    def as_calendar_event(self) -> CalendarEvent:
        """Return the booked slot as a calendar event belonging to this child."""
        return CalendarEvent(
            id=self.meeting_id,
            title=self.title,
            start_datetime=self.start_datetime,
            end_datetime=self.end_datetime,
            teacher_name=None,
            has_substitute=False,
            substitute_name=None,
            location=self.location,
            belongs_to=self.child_id,
            event_type=self.meeting_type,
            _raw=self._raw,
        )


def replace_booked_meetings(
    events: list[CalendarEvent], bookings: list[MeetingBooking]
) -> list[CalendarEvent]:
    """Show one child's booked slots in place of the meetings' booking periods.

    ``events`` and ``bookings`` are the same child's. Aula's calendar row for a
    parent meeting spans the whole booking period, often days. Each meeting the
    child has booked is replaced by its booked slots, appended after the other
    events. A meeting without a booking, such as an invitation not yet answered,
    stays as the calendar shows it. A new list is returned.
    """
    booked = {booking.meeting_id for booking in bookings}
    kept = [e for e in events if not (e.id in booked and e.event_type in MEETING_TYPES)]
    return kept + [booking.as_calendar_event() for booking in bookings]


def _interval(start: str, end: str) -> tuple[datetime, datetime]:
    beginning, ending = datetime.fromisoformat(start), datetime.fromisoformat(end)
    if beginning.utcoffset() is None or ending.utcoffset() is None or ending <= beginning:
        raise ValueError("Meeting timestamps must include an offset and a positive duration")
    return beginning, ending


def meeting_bookings(rows: list[dict[str, Any]], child_id: int) -> list[MeetingBooking]:
    """Resolve bookings from API rows, retaining only the requested child.

    Meeting row timestamps can span the entire booking period. The answer's
    selectedTimeSlotIndex points into the explicit interval list, including
    breaks. Guardian answers and repeated rows can describe the same booking.
    """
    resolved: dict[tuple, MeetingBooking] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = row.get("type")
        if not isinstance(kind, str) or kind not in MEETING_TYPES:
            continue
        try:
            intervals = []
            slots = row.get("timeSlot")
            if slots is None:
                if str(child_id) in {str(p) for p in row.get("belongsToProfiles") or []}:
                    intervals.append(_interval(row["startDateTime"], row["endDateTime"]))
            elif isinstance(slots, dict):
                for slot in slots.get("timeSlots") or []:
                    if not isinstance(slot, dict):
                        continue
                    choices = slot.get("timeSlotIndexes") or []
                    for answer in slot.get("answers") or []:
                        if not isinstance(answer, dict):
                            continue
                        if str(answer.get("concerningProfileId")) != str(child_id):
                            continue
                        index = answer.get("selectedTimeSlotIndex")
                        if type(index) is not int or not 0 <= index < len(choices):
                            _LOGGER.warning("Invalid booking index for meeting %s", row.get("id"))
                            continue
                        try:
                            choice = choices[index]
                            intervals.append(_interval(choice["startTime"], choice["endTime"]))
                        except KeyError, TypeError, ValueError:
                            _LOGGER.warning("Invalid booked interval for meeting %s", row.get("id"))
            for start, end in intervals:
                booking = MeetingBooking(
                    meeting_id=row["id"],
                    child_id=child_id,
                    title=row.get("title") or "Samtale",
                    meeting_type=row["type"],
                    start_datetime=start,
                    end_datetime=end,
                    location=get_in(row, "primaryResource.name") or row.get("primaryResourceText"),
                    _raw=row,
                )
                resolved[(booking.meeting_id, start, end)] = booking
        except KeyError, TypeError, ValueError:
            _LOGGER.warning("Skipping malformed meeting %s", row.get("id"))
    return sorted(resolved.values(), key=lambda booking: booking.start_datetime)
