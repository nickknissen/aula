"""Tests for aula.models.mu_weekly_letter."""

from aula.models.mu_weekly_letter import (
    MUWeeklyInstitution,
    MUWeeklyLetter,
    MUWeeklyPerson,
)


def test_mu_weekly_letter_from_dict():
    data = {
        "tilknytningId": 1,
        "tilknytningNavn": "Group A",
        "indhold": "<p>Weekly update</p>",
        "uge": 5,
        "sortOrder": 1,
    }
    letter = MUWeeklyLetter.from_dict(data)
    assert letter.group_id == 1
    assert letter.group_name == "Group A"
    assert letter.content_html == "<p>Weekly update</p>"
    assert letter.week_number == 5
    assert letter.sort_order == 1
    assert letter._raw is data


def test_mu_weekly_letter_from_dict_defaults():
    data = {}
    letter = MUWeeklyLetter.from_dict(data)
    assert letter.group_id == 0
    assert letter.group_name == ""
    assert letter.content_html == ""
    assert letter.week_number == 0


def test_mu_weekly_institution_from_dict():
    data = {
        "navn": "School A",
        "kode": 123,
        "ugebreve": [
            {"tilknytningId": 1, "tilknytningNavn": "G", "indhold": "", "uge": 5, "sortOrder": 0},
        ],
    }
    inst = MUWeeklyInstitution.from_dict(data)
    assert inst.name == "School A"
    assert inst.code == 123
    assert len(inst.letters) == 1
    assert inst.letters[0].group_name == "G"
    assert inst._raw is data


def test_mu_weekly_institution_from_dict_empty():
    data = {}
    inst = MUWeeklyInstitution.from_dict(data)
    assert inst.name == ""
    assert inst.code == 0
    assert inst.letters == []


def test_mu_weekly_person_from_dict():
    data = {
        "navn": "Student A",
        "id": 42,
        "uniLogin": "student01",
        "institutioner": [
            {"navn": "School", "kode": 1, "ugebreve": []},
        ],
    }
    person = MUWeeklyPerson.from_dict(data)
    assert person.name == "Student A"
    assert person.id == 42
    assert person.unilogin == "student01"
    assert len(person.institutions) == 1
    assert person.institutions[0].name == "School"
    assert person._raw is data


def test_mu_weekly_person_from_dict_empty():
    data = {}
    person = MUWeeklyPerson.from_dict(data)
    assert person.name == ""
    assert person.id == 0
    assert person.institutions == []


def test_mu_weekly_letter_dict_conversion():
    letter = MUWeeklyLetter(
        group_id=1, group_name="Group", content_html="<p>Hi</p>",
        week_number=5, sort_order=1,
    )
    result = dict(letter)
    assert result["group_name"] == "Group"
    assert "_raw" not in result
