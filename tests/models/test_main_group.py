"""Tests for aula.models.main_group."""

from aula.models.main_group import MainGroup


def test_main_group_from_dict():
    data = {
        "id": 1,
        "name": "Group A",
        "shortName": "GA",
        "institutionCode": "ABC",
        "institutionName": "School",
        "uniGroupType": "class",
    }
    mg = MainGroup.from_dict(data)
    assert mg.id == 1
    assert mg.name == "Group A"
    assert mg.short_name == "GA"
    assert mg.institution_code == "ABC"
    assert mg.institution_name == "School"
    assert mg.uni_group_type == "class"


def test_main_group_from_dict_minimal():
    data = {}
    mg = MainGroup.from_dict(data)
    assert mg.id is None
    assert mg.name is None
    assert mg.short_name is None


def test_main_group_creation():
    mg = MainGroup(id=1, name="Group A")
    result = dict(mg)
    assert result["name"] == "Group A"
    assert result["id"] == 1
    assert "_raw" not in result
