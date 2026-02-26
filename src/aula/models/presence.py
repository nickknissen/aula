from enum import Enum

_DISPLAY_NAMES: dict[int, tuple[str, str]] = {
    0: ("Not Present", "Ikke kommet"),
    1: ("Sick", "Syg"),
    2: ("Reported Absent", "Ferie/fri"),
    3: ("Present", "Til stede"),
    4: ("Field Trip", "På tur"),
    5: ("Sleeping", "Sover"),
    6: ("Spare Time Activity", "Til aktivitet"),
    7: ("Physical Placement", "Fysisk placering"),
    8: ("Checked Out", "Gået"),
}


class PresenceState(Enum):
    NOT_PRESENT = 0
    SICK = 1
    REPORTED_ABSENT = 2
    PRESENT = 3
    FIELDTRIP = 4
    SLEEPING = 5
    SPARE_TIME_ACTIVITY = 6
    PHYSICAL_PLACEMENT = 7
    CHECKED_OUT = 8

    @property
    def display_name(self) -> str:
        """Return a user-friendly English display name."""
        return _DISPLAY_NAMES[self.value][0]

    @property
    def danish_name(self) -> str:
        """Return the Danish display name."""
        return _DISPLAY_NAMES[self.value][1]

    @classmethod
    def get_display_name(cls, value: int) -> str:
        """Return a user-friendly display name for the status value."""
        try:
            return cls(value).display_name
        except ValueError:
            return "Unknown Status"
