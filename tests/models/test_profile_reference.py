"""Tests for aula.models.profile_reference."""

from aula.models.profile_reference import ProfileReference


def test_profile_reference_from_dict():
    data = {
        "id": 1,
        "profileId": 100,
        "firstName": "John",
        "lastName": "Doe",
        "fullName": "John Doe",
        "shortName": "JD",
        "role": "guardian",
        "institution": {"institutionName": "School A"},
        "profilePicture": {"url": "pic.jpg"},
    }
    ref = ProfileReference.from_dict(data)
    assert ref.id == 1
    assert ref.profile_id == 100
    assert ref.first_name == "John"
    assert ref.last_name == "Doe"
    assert ref.full_name == "John Doe"
    assert ref.short_name == "JD"
    assert ref.role == "guardian"
    assert ref.institution_name == "School A"
    assert ref.profile_picture == {"url": "pic.jpg"}
    assert ref._raw is data


def test_profile_reference_from_dict_minimal():
    data = {"id": 2, "profileId": 200}
    ref = ProfileReference.from_dict(data)
    assert ref.id == 2
    assert ref.profile_id == 200
    assert ref.first_name == ""
    assert ref.last_name == ""
    assert ref.full_name == ""
    assert ref.institution_name == ""
    assert ref.profile_picture is None


def test_profile_reference_from_dict_empty_institution():
    data = {"id": 1, "profileId": 1, "institution": {}}
    ref = ProfileReference.from_dict(data)
    assert ref.institution_name == ""


def test_profile_reference_dict_conversion():
    ref = ProfileReference(
        id=1, profile_id=100, first_name="John", last_name="Doe",
        full_name="John Doe", short_name="JD", role="guardian",
        institution_name="School",
    )
    result = dict(ref)
    assert result["full_name"] == "John Doe"
    assert result["role"] == "guardian"
    assert "_raw" not in result
