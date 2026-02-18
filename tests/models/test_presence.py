"""Tests for aula.models.presence."""

from aula.models.presence import PresenceState


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
