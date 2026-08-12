"""Tests for aula.models.easyiq_homework."""

from aula.models.easyiq_calendar_event import EasyIQCalendarEvent
from aula.models.easyiq_homework import EasyIQHomework


def test_easyiq_homework_from_dict():
    data = {
        "id": "hw-1",
        "title": "Read chapter 5",
        "description": "<p>Pages 40-55</p>",
        "dueDate": "2026-02-28",
        "subject": "Danish",
        "isCompleted": False,
    }
    hw = EasyIQHomework.from_dict(data)
    assert hw.id == "hw-1"
    assert hw.title == "Read chapter 5"
    assert hw.description == "<p>Pages 40-55</p>"
    assert hw.due_date == "2026-02-28"
    assert hw.subject == "Danish"
    assert hw.is_completed is False
    assert hw._raw is data


def test_easyiq_homework_from_dict_defaults():
    data = {}
    hw = EasyIQHomework.from_dict(data)
    assert hw.id == ""
    assert hw.title == ""
    assert hw.description == ""
    assert hw.due_date == ""
    assert hw.subject == ""
    assert hw.is_completed is False


def test_easyiq_homework_from_dict_completed():
    data = {"id": "hw-2", "title": "Essay", "isCompleted": True}
    hw = EasyIQHomework.from_dict(data)
    assert hw.is_completed is True


def test_easyiq_homework_from_calendar_event():
    raw = {
        "itemType": 4,
        "id": "evt-9",
        "start": "2026-02-28T00:00:00",
        "courses": "Dansk",
        "description": "<p>Pages 40-55</p>",
    }
    hw = EasyIQHomework.from_calendar_event(EasyIQCalendarEvent.from_dict(raw))
    assert hw.id == "evt-9"
    assert hw.title == "Dansk"
    assert hw.subject == "Dansk"
    assert hw.description == "<p>Pages 40-55</p>"
    assert hw.due_date == "2026-02-28T00:00:00"
    assert hw.is_completed is False
    assert hw._raw is raw


def test_easyiq_homework_keeps_the_class():
    """ActivitiesDisplay says which class the homework was set for."""
    event = EasyIQCalendarEvent.from_dict(
        {"ItemType": 4, "CoursesDisplay": "Dansk", "ActivitiesDisplay": "7-9F"}
    )
    hw = EasyIQHomework.from_calendar_event(event)
    assert hw.activities == "7-9F"
    assert dict(hw)["activities"] == "7-9F"


def test_easyiq_homework_from_calendar_event_without_an_id():
    """Portal rows carry no assignment id, so the start timestamp stands in."""
    event = EasyIQCalendarEvent.from_dict({"itemType": 4, "start": "2026-02-28T00:00:00"})
    assert EasyIQHomework.from_calendar_event(event).id == "2026-02-28T00:00:00"


def test_easyiq_homework_dict_conversion():
    hw = EasyIQHomework(
        id="hw-1",
        title="Read chapter 5",
        description="Pages 40-55",
        due_date="2026-02-28",
        subject="Danish",
        is_completed=False,
    )
    result = dict(hw)
    assert result["title"] == "Read chapter 5"
    assert result["due_date"] == "2026-02-28"
    assert "_raw" not in result
