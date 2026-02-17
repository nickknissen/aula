from enum import Enum


class PresenceState(Enum):
    NOT_PRESENT = 0  # Ikke kommet
    SICK = 1  # Syg
    REPORTED_ABSENT = 2  # Ferie/fri
    PRESENT = 3  # Til stede
    FIELDTRIP = 4  # Pa tur
    SLEEPING = 5  # Sover
    SPARE_TIME_ACTIVITY = 6  # Til aktivitet
    PHYSICAL_PLACEMENT = 7  # Fysisk placering
    CHECKED_OUT = 8  # Gaaet

    @classmethod
    def get_display_name(cls, value: int) -> str:
        """Return a user-friendly display name for the status value."""
        try:
            member = cls(value)
            # Replace underscores with spaces and capitalize words for display
            return member.name.replace("_", " ").title()
        except ValueError:
            return "Unknown Status"
