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
    assert child.user_id is None
    assert child.institution_code is None


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
    assert result["user_id"] is None
    assert result["institution_code"] is None
    assert "_raw" not in result


def test_child_from_dict_null_nested():
    """Aula sends null — not a missing key — for a child without a profile picture."""
    data = {
        "id": 4,
        "profileId": 400,
        "name": "Diana",
        "userId": None,
        "institutionProfile": None,
        "profilePicture": None,
    }
    child = Child.from_dict(data)
    assert child.institution_name == ""
    assert child.profile_picture == ""
    assert child.user_id is None
    assert child.institution_code is None


def test_child_from_dict_identifiers_for_widget_calls():
    data = {
        "id": 5,
        "profileId": 500,
        "name": "Eve",
        "userId": "fake0001",
        "institutionProfile": {"institutionName": "School A", "institutionCode": "999999"},
    }
    child = Child.from_dict(data)
    assert child.user_id == "fake0001"
    assert child.institution_code == "999999"


def test_child_from_dict_numeric_identifiers_become_strings():
    data = {
        "id": 6,
        "profileId": 600,
        "name": "Finn",
        "userId": 123456,
        "institutionProfile": {"institutionCode": 999999},
    }
    child = Child.from_dict(data)
    assert child.user_id == "123456"
    assert child.institution_code == "999999"


def test_custody_flag_is_read_from_aula():
    """The portal only lets a guardian with custody or extended access register an absence."""
    data = {"id": 7, "profileId": 700, "name": "Barn Et"}
    assert Child.from_dict(
        {**data, "hasCustodyOrExtendedAccess": True}
    ).has_custody_or_extended_access
    assert (
        Child.from_dict(
            {**data, "hasCustodyOrExtendedAccess": False}
        ).has_custody_or_extended_access
        is False
    )


def test_missing_custody_flag_is_unknown_rather_than_denied():
    """A profile without the field must not read as a guardian without custody."""
    child = Child.from_dict({"id": 8, "profileId": 800, "name": "Barn To"})
    assert child.has_custody_or_extended_access is None
    assert Child(1, 2, "Barn To", "", "").has_custody_or_extended_access is None
