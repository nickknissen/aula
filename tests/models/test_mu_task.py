"""Tests for aula.models.mu_task."""

from aula.models.mu_task import MUTask, MUTaskClass, MUTaskCourse, _parse_dotnet_date


def test_parse_dotnet_date_valid():
    result = _parse_dotnet_date("/Date(1609459200000)/")
    assert result is not None
    assert result.year == 2021
    assert result.month == 1
    assert result.day == 1


def test_parse_dotnet_date_with_offset():
    result = _parse_dotnet_date("/Date(1609459200000-0000)/")
    assert result is not None
    assert result.year == 2021


def test_parse_dotnet_date_none():
    assert _parse_dotnet_date(None) is None


def test_parse_dotnet_date_empty():
    assert _parse_dotnet_date("") is None


def test_parse_dotnet_date_invalid():
    assert _parse_dotnet_date("invalid") is None


def test_mu_task_class_from_dict():
    data = {"id": 1, "navn": "Math", "fagId": 10, "fagNavn": "Mathematics"}
    tc = MUTaskClass.from_dict(data)
    assert tc.id == 1
    assert tc.name == "Math"
    assert tc.subject_id == 10
    assert tc.subject_name == "Mathematics"
    assert tc._raw is data


def test_mu_task_class_from_dict_defaults():
    data = {}
    tc = MUTaskClass.from_dict(data)
    assert tc.id == 0
    assert tc.name == ""
    assert tc.subject_id == 0


def test_mu_task_course_from_dict():
    data = {
        "id": "c1",
        "navn": "Course A",
        "ikon": "icon.png",
        "aarsplanId": "5",
        "farve": "#fff",
        "url": "https://example.com",
    }
    course = MUTaskCourse.from_dict(data)
    assert course.id == "c1"
    assert course.name == "Course A"
    assert course.icon == "icon.png"
    assert course.yearly_plan_id == "5"
    assert course.color == "#fff"
    assert course.url == "https://example.com"
    assert course._raw is data


def test_mu_task_course_from_dict_defaults():
    data = {}
    course = MUTaskCourse.from_dict(data)
    assert course.id == ""
    assert course.name == ""
    assert course.color is None
    assert course.url is None


def test_mu_task_from_dict():
    data = {
        "id": "t1",
        "title": "Homework",
        "opgaveType": "assignment",
        "afleveringsdato": "/Date(1609459200000)/",
        "ugedag": "Monday",
        "ugenummer": 5,
        "erFaerdig": False,
        "kuvertnavn": "Alice",
        "unilogin": "alice01",
        "url": "https://example.com/task",
        "hold": [{"id": 1, "navn": "Math", "fagId": 10, "fagNavn": "Mathematics"}],
        "forloeb": {
            "id": "c1", "navn": "Course", "ikon": "",
            "aarsplanId": "", "farve": None, "url": None,
        },
    }
    task = MUTask.from_dict(data)
    assert task.id == "t1"
    assert task.title == "Homework"
    assert task.task_type == "assignment"
    assert task.due_date is not None
    assert task.due_date.year == 2021
    assert task.weekday == "Monday"
    assert task.week_number == 5
    assert task.is_completed is False
    assert task.student_name == "Alice"
    assert task.unilogin == "alice01"
    assert len(task.classes) == 1
    assert task.classes[0].name == "Math"
    assert task.course is not None
    assert task.course.name == "Course"
    assert task._raw is data


def test_mu_task_from_dict_minimal():
    data = {"id": "t2"}
    task = MUTask.from_dict(data)
    assert task.id == "t2"
    assert task.title == ""
    assert task.due_date is None
    assert task.classes == []
    assert task.course is None
