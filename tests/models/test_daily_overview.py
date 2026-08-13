"""Tests for aula.models.daily_overview."""

from aula.models.daily_overview import DailyOverview
from aula.models.presence import PresenceState
from aula.models.presence_location import PresenceLocation

# The shape Aula actually sends, matching PresenceLocationDto in the Android app.
LOCATION_PAYLOAD = {
    "id": 4321,
    "name": "Ude",
    "description": "",
    "symbol": "icon-Aula_sfo_slide",
    "startTime": None,
    "endTime": None,
    "isDeactivated": False,
}


def test_daily_overview_from_dict_full():
    data = {
        "id": 1,
        "status": 3,
        "location": LOCATION_PAYLOAD,
        "sleepIntervals": [{"start": "10:00", "end": "11:00"}],
        "checkInTime": "08:00",
        "checkOutTime": "16:00",
        "entryTime": "07:55",
        "exitTime": "16:05",
        "exitWith": "Parent",
        "comment": "Good day",
        "institutionProfile": {
            "profileId": 10,
            "institutionName": "School",
            "role": "student",
        },
        "mainGroup": {"id": 5, "name": "Class A"},
    }
    overview = DailyOverview.from_dict(data)
    assert overview.id == 1
    assert overview.status == PresenceState.PRESENT
    assert overview.location is not None
    assert overview.location.id == 4321
    assert overview.location.name == "Ude"
    assert overview.location.symbol == "icon-Aula_sfo_slide"
    assert overview.location._raw is LOCATION_PAYLOAD
    assert overview.sleep_intervals == [{"start": "10:00", "end": "11:00"}]
    assert overview.check_in_time == "08:00"
    assert overview.check_out_time == "16:00"
    assert overview.entry_time == "07:55"
    assert overview.exit_time == "16:05"
    assert overview.exit_with == "Parent"
    assert overview.comment == "Good day"
    assert overview.institution_profile is not None
    assert overview.institution_profile.institution_name == "School"
    assert overview.main_group is not None
    assert overview.main_group.name == "Class A"
    assert overview._raw is data


def test_daily_overview_from_dict_minimal():
    data = {}
    overview = DailyOverview.from_dict(data)
    assert overview.id is None
    assert overview.status is None
    assert overview.institution_profile is None
    assert overview.main_group is None
    assert overview.sleep_intervals == []


def test_daily_overview_unknown_status():
    data = {"status": 999}
    overview = DailyOverview.from_dict(data)
    assert overview.status is None


def test_daily_overview_dict_conversion():
    overview = DailyOverview(id=1, location=PresenceLocation(id=7, name="Hal"))
    result = dict(overview)
    assert result["id"] == 1
    assert result["location"] == {
        "id": 7,
        "name": "Hal",
        "description": "",
        "symbol": "",
    }
    assert "_raw" not in result


def test_daily_overview_location_absent():
    overview = DailyOverview.from_dict({"status": 3})
    assert overview.location is None


def test_daily_overview_location_string_fallback():
    """No response is known to send a bare string, but it must not break parsing."""
    overview = DailyOverview.from_dict({"location": "Room A"})
    assert overview.location is not None
    assert overview.location.name == "Room A"
    assert overview.location.id is None
