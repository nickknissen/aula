"""Tests for aula.models.docendo_weekplan."""

import datetime

import pytest

from aula.models import DocendoWeekPlan


def _plan(**overrides):
    data = {
        "name": "4A",
        "note": "<p>Note til ugen</p>",
        "events": [
            {
                "startTime": "2026-10-27T07:00:00Z",
                "endTime": "2026-10-27T08:30:00Z",
                "title": "Matematik",
                "description": "<p>Brøker</p>",
                "learningGoal": "",
                "notesForStudents": "",
            },
            {
                "startTime": "2026-10-26T08:30:00",
                "endTime": "2026-10-26T08:45:00",
                "title": "Fællespause",
                "description": "",
                "learningGoal": None,
                "notesForStudents": "",
            },
        ],
    }
    data.update(overrides)
    return data


def test_parses_plan_and_sorts_lessons_by_start():
    plan = DocendoWeekPlan.from_dict(_plan())

    assert plan.name == "4A"
    assert plan.note == "<p>Note til ugen</p>"
    assert [lesson.title for lesson in plan.lessons] == ["Fællespause", "Matematik"]


def test_times_are_utc_even_without_an_offset():
    pause, maths = DocendoWeekPlan.from_dict(_plan()).lessons

    assert pause.start_time == datetime.datetime(2026, 10, 26, 8, 30, tzinfo=datetime.UTC)
    assert maths.end_time == datetime.datetime(2026, 10, 27, 8, 30, tzinfo=datetime.UTC)


def test_lessons_without_plan_text_have_no_content():
    pause, maths = DocendoWeekPlan.from_dict(_plan()).lessons

    assert pause.has_content is False
    assert maths.has_content is True


def test_malformed_events_are_skipped():
    plan = DocendoWeekPlan.from_dict(_plan(events=["junk", {"title": "Dansk", "startTime": "x"}]))

    assert len(plan.lessons) == 1
    assert plan.lessons[0].start_time is None


def test_events_that_are_not_a_list_give_no_lessons():
    assert DocendoWeekPlan.from_dict(_plan(events=None)).lessons == []


@pytest.mark.parametrize(
    ("class_name", "expected"),
    [("4A", True), ("4.a", True), (" 4 A ", True), ("4B", False), ("", False), (None, False)],
)
def test_matches_class_ignores_case_spaces_and_punctuation(class_name, expected):
    assert DocendoWeekPlan.from_dict(_plan()).matches_class(class_name) is expected
