"""Tests for aula.models.presence."""

import pytest

from aula.models.presence import (
    ActivityType,
    PresenceDashboard,
    PresenceModule,
    PresenceModulePermission,
    PresenceState,
)


def test_presence_state_values():
    assert PresenceState.NOT_PRESENT.value == 0
    assert PresenceState.SICK.value == 1
    assert PresenceState.REPORTED_ABSENT.value == 2
    assert PresenceState.PRESENT.value == 3
    assert PresenceState.FIELDTRIP.value == 4
    assert PresenceState.SLEEPING.value == 5
    assert PresenceState.SPARE_TIME_ACTIVITY.value == 6
    assert PresenceState.PHYSICAL_PLACEMENT.value == 7
    assert PresenceState.CHECKED_OUT.value == 8
    assert PresenceState.NOT_ARRIVED.value == 9


def test_presence_state_covers_the_app_enum_range():
    """The app enum runs 0-9 as states; 10 ("All") is a filter, not a state."""
    assert [s.value for s in PresenceState] == list(range(10))
    with pytest.raises(ValueError, match="10"):
        PresenceState(10)


def test_presence_state_not_arrived_names():
    assert PresenceState.NOT_ARRIVED.display_name == "Not Arrived"
    assert PresenceState.NOT_ARRIVED.danish_name == "Ikke mødt"
    assert PresenceState.get_display_name(9) == "Not Arrived"


def test_presence_state_display_name_present():
    name = PresenceState.get_display_name(3)
    assert name == "Present"


def test_presence_state_display_name_sick():
    name = PresenceState.get_display_name(1)
    assert name == "Sick"


def test_presence_state_display_name_not_present():
    name = PresenceState.get_display_name(0)
    assert name == "Not Present"


def test_presence_state_display_name_unknown():
    name = PresenceState.get_display_name(99)
    assert name == "Unknown Status"


def test_presence_state_from_value():
    state = PresenceState(3)
    assert state == PresenceState.PRESENT
    assert state.name == "PRESENT"


def test_presence_state_display_name_property():
    assert PresenceState.NOT_PRESENT.display_name == "Not Present"
    assert PresenceState.FIELDTRIP.display_name == "Field Trip"
    assert PresenceState.CHECKED_OUT.display_name == "Checked Out"


def test_presence_state_danish_name_property():
    assert PresenceState.NOT_PRESENT.danish_name == "Ikke kommet"
    assert PresenceState.SICK.danish_name == "Syg"
    assert PresenceState.REPORTED_ABSENT.danish_name == "Ferie/fri"
    assert PresenceState.PRESENT.danish_name == "Til stede"
    assert PresenceState.FIELDTRIP.danish_name == "På tur"
    assert PresenceState.SLEEPING.danish_name == "Sover"
    assert PresenceState.SPARE_TIME_ACTIVITY.danish_name == "Til aktivitet"
    assert PresenceState.PHYSICAL_PLACEMENT.danish_name == "Fysisk placering"
    assert PresenceState.CHECKED_OUT.danish_name == "Gået"


def test_presence_module_wire_values():
    """Values must match the moduleType strings Aula sends."""
    assert PresenceModule.REPORT_SICK.value == "report_sick"
    assert PresenceModule.VACATION.value == "vacation"
    assert PresenceModule.PICKUP_TIMES.value == "pickup_times"
    assert PresenceModule.DROP_OFF_TIME.value == "drop_off_time"
    assert PresenceModule.DAILY_MESSAGE.value == "daily_message"
    assert PresenceModule.FIELD_TRIP.value == "field_trip"
    assert PresenceModule.SPARE_TIME_ACTIVITY.value == "spare_time_activity"
    assert PresenceModule.LOCATION.value == "location"
    assert PresenceModule.SLEEP.value == "sleep"
    assert PresenceModule.PICKUP_TYPE.value == "pickup_type"


def test_presence_module_permission_wire_values():
    assert PresenceModulePermission.DEACTIVATED.value == "deactivated"
    assert PresenceModulePermission.READABLE.value == "readable"
    assert PresenceModulePermission.EDITABLE.value == "editable"


def test_presence_dashboard_wire_values():
    assert PresenceDashboard.GUARDIAN.value == "guardian_dashboard"
    assert PresenceDashboard.EMPLOYEE.value == "employee_dashboard"
    assert PresenceDashboard.CHECK_IN.value == "check_in_dashboard"


def test_activity_type_values():
    assert ActivityType.PICKED_UP_BY.value == 0
    assert ActivityType.SELF_DECIDER.value == 1
    assert ActivityType.SEND_HOME.value == 2
    assert ActivityType.GO_HOME_WITH.value == 3
    assert ActivityType.DROP_OFF_TIME.value == 4


def test_activity_type_from_value():
    activity = ActivityType(3)
    assert activity == ActivityType.GO_HOME_WITH
    assert activity.name == "GO_HOME_WITH"


def test_activity_type_display_name_property():
    assert ActivityType.PICKED_UP_BY.display_name == "Collected By"
    assert ActivityType.SELF_DECIDER.display_name == "Self Decider"
    assert ActivityType.SEND_HOME.display_name == "Sent Home"
    assert ActivityType.GO_HOME_WITH.display_name == "Goes Home With"
    assert ActivityType.DROP_OFF_TIME.display_name == "Drop-off Time"


def test_activity_type_danish_name_property():
    assert ActivityType.PICKED_UP_BY.danish_name == "Hentes af"
    assert ActivityType.SELF_DECIDER.danish_name == "Selvbestemmer"
    assert ActivityType.SEND_HOME.danish_name == "Sendes hjem"
    assert ActivityType.GO_HOME_WITH.danish_name == "Går hjem med"
    assert ActivityType.DROP_OFF_TIME.danish_name == "Afleveringstid"


def test_activity_type_get_display_name():
    assert ActivityType.get_display_name(0) == "Collected By"
    assert ActivityType.get_display_name(4) == "Drop-off Time"


def test_activity_type_get_display_name_unknown():
    assert ActivityType.get_display_name(99) == "Unknown Activity Type"


def test_activity_type_unknown_value_raises():
    with pytest.raises(ValueError, match="99"):
        ActivityType(99)


def test_activity_type_requires_exit_with():
    assert ActivityType.PICKED_UP_BY.requires_exit_with is True
    assert ActivityType.GO_HOME_WITH.requires_exit_with is True


def test_activity_type_does_not_require_exit_with():
    assert ActivityType.SELF_DECIDER.requires_exit_with is False
    assert ActivityType.SEND_HOME.requires_exit_with is False
    assert ActivityType.DROP_OFF_TIME.requires_exit_with is False
