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


def test_appointment_from_dict_defaults():
    data = {}
    appt = Appointment.from_dict(data)
    assert appt.appointment_id == ""
    assert appt.title == ""
    assert appt.start == ""
    assert appt.end == ""
    assert appt.description == ""
    assert appt.item_type is None


def test_appointment_dict_conversion():
    appt = Appointment(
        appointment_id="apt-1",
        title="Math",
        start="08:00",
        end="09:00",
        description="Algebra",
        item_type=9,
    )
    result = dict(appt)
    assert result["title"] == "Math"
    assert result["start"] == "08:00"
    assert result["item_type"] == 9
    assert "_raw" not in result
