"""Tests for aula.models.easyiq_homework."""

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
