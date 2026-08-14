"""Tests for aula.models.mu_task."""

from aula.models.mu_task import (
    MUTask,
    MUTaskClass,
    MUTaskCourse,
    _parse_dotnet_date,
    decode_mu_deep_link,
)


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
            "id": "c1",
            "navn": "Course",
            "ikon": "",
            "aarsplanId": "",
            "farve": None,
            "url": None,
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


class TestDecodeMuDeepLink:
    """An opgave's raw ``url`` is an SSO wrapper; the usable link is inside it."""

    def test_decodes_the_last_path_segment(self):
        url = (
            "https://api.minuddannelse.net/aula/redirect/123456/"
            "aHR0cHMlM2ElMmYlMmZ3d3cubWludWRkYW5uZWxzZS5uZXQlMmZOb2RlJTJmbWludWdlJTJmMTIzNDU2"
            "NyUzZnVnZSUzZDIwMjYtVzMz"
        )
        assert (
            decode_mu_deep_link(url)
            == "https://www.minuddannelse.net/Node/minuge/1234567?uge=2026-W33"
        )

    def test_pads_a_segment_whose_length_is_not_a_multiple_of_four(self):
        import base64

        target = "https://www.minuddannelse.net/Node/minuge/1"
        segment = base64.b64encode(target.encode()).decode().rstrip("=")
        assert len(segment) % 4 != 0, "fixture should need padding to be decodable"

        assert decode_mu_deep_link(f"https://api.minuddannelse.net/aula/redirect/1/{segment}")

    def test_malformed_base64_gives_none(self):
        assert decode_mu_deep_link("not-a-valid-deeplink") is None

    def test_ordinary_url_path_segment_is_not_decoded(self):
        """A plain URL must not be mangled into something that looks like a link."""
        assert decode_mu_deep_link("https://www.minuddannelse.net/Node/minuge/1234567") is None

    def test_decoded_value_that_is_not_a_url_gives_none(self):
        import base64

        segment = base64.b64encode(b"just some text").decode()
        assert (
            decode_mu_deep_link(f"https://api.minuddannelse.net/aula/redirect/1/{segment}") is None
        )

    def test_non_utf8_payload_gives_none(self):
        import base64

        segment = base64.b64encode(b"\xff\xfe\xfd\xfc").decode()
        assert (
            decode_mu_deep_link(f"https://api.minuddannelse.net/aula/redirect/1/{segment}") is None
        )

    def test_empty_and_missing_urls_give_none(self):
        assert decode_mu_deep_link("") is None
        assert decode_mu_deep_link(None) is None

    def test_url_ending_in_a_separator_gives_none(self):
        assert decode_mu_deep_link("https://api.minuddannelse.net/aula/redirect/123456/") is None

    def test_url_with_no_path_separator_gives_none(self):
        assert decode_mu_deep_link("nopath") is None


class TestMuTaskDeepLink:
    def test_from_dict_exposes_the_decoded_link_and_keeps_url(self):
        raw_url = (
            "https://api.minuddannelse.net/aula/redirect/123456/"
            "aHR0cHMlM2ElMmYlMmZ3d3cubWludWRkYW5uZWxzZS5uZXQlMmZOb2RlJTJmbWludWdlJTJmMTIzNDU2"
            "NyUzZnVnZSUzZDIwMjYtVzMz"
        )
        task = MUTask.from_dict({"id": "1", "url": raw_url})

        assert task.url == raw_url
        assert task.deep_link == "https://www.minuddannelse.net/Node/minuge/1234567?uge=2026-W33"

    def test_undecodable_url_is_kept_verbatim_with_no_link(self):
        task = MUTask.from_dict({"id": "1", "url": "not-a-valid-deeplink"})

        assert task.url == "not-a-valid-deeplink"
        assert task.deep_link is None

    def test_missing_url_leaves_both_empty(self):
        task = MUTask.from_dict({"id": "1"})

        assert task.url == ""
        assert task.deep_link is None

    def test_deep_link_is_serialised_for_json_consumers(self):
        task = MUTask.from_dict({"id": "1", "url": "not-a-valid-deeplink"})

        assert dict(task)["deep_link"] is None
