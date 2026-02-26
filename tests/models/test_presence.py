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
