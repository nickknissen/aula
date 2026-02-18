"""Tests for aula.models.child."""

from aula.models.child import Child


def test_child_from_dict():
    data = {
        "id": 1,
        "profileId": 100,
        "name": "Alice",
        "institutionProfile": {"institutionName": "School A"},
        "profilePicture": {"url": "https://example.com/pic.jpg"},
    }
    child = Child.from_dict(data)
    assert child.id == 1
    assert child.profile_id == 100
    assert child.name == "Alice"
    assert child.institution_name == "School A"
    assert child.profile_picture == "https://example.com/pic.jpg"
    assert child._raw is data


def test_child_from_dict_missing_optional():
    data = {"id": 2, "profileId": 200, "name": "Bob"}
    child = Child.from_dict(data)
    assert child.institution_name == ""
    assert child.profile_picture == ""


def test_child_from_dict_empty_nested():
    data = {
        "id": 3,
        "profileId": 300,
        "name": "Charlie",
        "institutionProfile": {},
        "profilePicture": {},
    }
    child = Child.from_dict(data)
    assert child.institution_name == ""
    assert child.profile_picture == ""


def test_child_dict_conversion():
    child = Child(id=1, profile_id=100, name="Test", institution_name="X", profile_picture="")
    result = dict(child)
    assert result["name"] == "Test"
    assert result["id"] == 1
    assert result["profile_id"] == 100
    assert "_raw" not in result
