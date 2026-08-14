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
    9: ("Not Arrived", "Ikke mødt"),
}


class PresenceState(Enum):
    """A child's presence status, as both read and written by Aula.

    Aula uses one enum for both directions: ``presence.getDailyOverview``
    reports these numbers and ``presence.updateStatusByInstitutionProfileIds``
    accepts them. Verified against the portal bundle (webpack module 31 of
    ``/static/js/0.*.js``, the only presence status enum the store imports) and
    against ``Enums.ComeGo.PresenceStatusEnum`` in the decompiled mobile app
    (``com.netcompany.aulanativeprivate``).

    ``NOT_ARRIVED`` exists only in the app enum; the portal's numeric enum stops
    at ``CHECKED_OUT``. It is carried here so an institution that does report it
    gets a name rather than "Unknown Status". The app's trailing ``All = 10`` is
    a filter sentinel, not a state, so it is deliberately absent.
    """

    NOT_PRESENT = 0
    SICK = 1
    REPORTED_ABSENT = 2
    PRESENT = 3
    FIELDTRIP = 4
    SLEEPING = 5
    SPARE_TIME_ACTIVITY = 6
    PHYSICAL_PLACEMENT = 7
    CHECKED_OUT = 8
    NOT_ARRIVED = 9

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


class PresenceModule(Enum):
    """A Komme/gå feature an institution can switch on or off per child.

    Wire values come from the portal bundle (webpack module 38) and match
    ``Enums.ComeGo.PresenceModuleSettingsModule`` in the mobile app. They appear
    as ``moduleType`` inside ``presenceConfiguration.dashboardModuleSettings``.
    """

    PICKUP_TIMES = "pickup_times"
    DROP_OFF_TIME = "drop_off_time"
    DAILY_MESSAGE = "daily_message"
    REPORT_SICK = "report_sick"
    VACATION = "vacation"
    FIELD_TRIP = "field_trip"
    SPARE_TIME_ACTIVITY = "spare_time_activity"
    LOCATION = "location"
    SLEEP = "sleep"
    PICKUP_TYPE = "pickup_type"


class PresenceModulePermission(Enum):
    """What the signed-in role may do with a :class:`PresenceModule`.

    ``READABLE`` shows the module without allowing changes; the portal only
    enables the write when the permission is ``EDITABLE``.
    """

    DEACTIVATED = "deactivated"
    READABLE = "readable"
    EDITABLE = "editable"


class PresenceDashboard(Enum):
    """Which dashboard a set of module permissions applies to.

    Permissions are per dashboard, so a guardian check must read the
    ``GUARDIAN`` entry: the employee dashboard may edit modules a guardian
    cannot.
    """

    GUARDIAN = "guardian_dashboard"
    EMPLOYEE = "employee_dashboard"
    CHECK_IN = "check_in_dashboard"


_ACTIVITY_DISPLAY_NAMES: dict[int, tuple[str, str]] = {
    0: ("Collected By", "Hentes af"),
    1: ("Self Decider", "Selvbestemmer"),
    2: ("Sent Home", "Sendes hjem"),
    3: ("Goes Home With", "Går hjem med"),
    4: ("Drop-off Time", "Afleveringstid"),
}


class ActivityType(Enum):
    """How a child leaves at the end of the day.

    Used by ``DayTemplate.activity_type`` and by
    ``AulaApiClient.update_presence_template``. ``PICKED_UP_BY`` and
    ``GO_HOME_WITH`` both require a name in ``exit_with``.
    """

    PICKED_UP_BY = 0
    SELF_DECIDER = 1
    SEND_HOME = 2
    GO_HOME_WITH = 3
    DROP_OFF_TIME = 4

    @property
    def display_name(self) -> str:
        """Return a user-friendly English display name."""
        return _ACTIVITY_DISPLAY_NAMES[self.value][0]

    @property
    def danish_name(self) -> str:
        """Return the Danish display name, as Aula labels it."""
        return _ACTIVITY_DISPLAY_NAMES[self.value][1]

    @property
    def requires_exit_with(self) -> bool:
        """Return True if Aula requires a named person in ``exit_with``."""
        return self in (ActivityType.PICKED_UP_BY, ActivityType.GO_HOME_WITH)

    @classmethod
    def get_display_name(cls, value: int) -> str:
        """Return a user-friendly display name for the activity type value."""
        try:
            return cls(value).display_name
        except ValueError:
            return "Unknown Activity Type"
