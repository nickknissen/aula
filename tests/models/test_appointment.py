"""Tests for aula.models.appointment."""

from aula.models.appointment import Appointment


def test_appointment_from_dict():
    data = {
        "appointmentId": "apt-1",
        "title": "Math Lesson",
        "start": "2026-02-24 08:00",
        "end": "2026-02-24 09:00",
        "description": "<p>Algebra</p>",
        "itemType": 9,
    }
    appt = Appointment.from_dict(data)
    assert appt.appointment_id == "apt-1"
    assert appt.title == "Math Lesson"
    assert appt.start == "2026-02-24 08:00"
    assert appt.end == "2026-02-24 09:00"
    assert appt.description == "<p>Algebra</p>"
    assert appt.item_type == 9
    assert appt._raw is data


def test_appointment_from_dict_preserves_easyiq_metadata():
    appt = Appointment.from_dict(
        {
            "appointmentId": "apt-1",
            "title": "Sports day",
            "ownerName": "Ada Teacher",
            "isAllDay": "yes",
            "isNotice": 1,
        }
    )

    assert appt.owner_name == "Ada Teacher"
    assert appt.is_all_day is True
    assert appt.is_notice is True


def test_appointment_metadata_round_trips_in_snake_case():
    original = Appointment(
        appointment_id="apt-1",
        title="Sports day",
        owner_name="Ada Teacher",
        is_all_day=True,
        is_notice=True,
    )

    restored = Appointment.from_dict(dict(original))

    assert restored.owner_name == "Ada Teacher"
    assert restored.is_all_day is True
    assert restored.is_notice is True


def test_appointment_from_dict_defaults():
    data = {}
    appt = Appointment.from_dict(data)
    assert appt.appointment_id == ""
    assert appt.title == ""
    assert appt.start == ""
    assert appt.end == ""
    assert appt.description == ""
    assert appt.item_type is None
    assert appt.owner_name == ""
    assert appt.is_all_day is False
    assert appt.is_notice is False


def test_appointment_booleans_reject_unknown_encodings():
    for value in (False, "false", "0", 0, "sometimes", None):
        appt = Appointment.from_dict({"isAllDay": value, "isNotice": value})
        assert appt.is_all_day is False
        assert appt.is_notice is False


def test_appointment_dict_conversion():
    appt = Appointment(
        appointment_id="apt-1",
        title="Math",
        start="08:00",
        end="09:00",
        description="Algebra",
        item_type=9,
        owner_name="Ada Teacher",
        is_all_day=True,
        is_notice=True,
    )
    result = dict(appt)
    assert result["title"] == "Math"
    assert result["start"] == "08:00"
    assert result["item_type"] == 9
    assert result["owner_name"] == "Ada Teacher"
    assert result["is_all_day"] is True
    assert result["is_notice"] is True
    assert "_raw" not in result
