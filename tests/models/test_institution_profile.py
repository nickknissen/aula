"""Tests for aula.models.institution_profile."""

from aula.models.institution_profile import InstitutionProfile


def test_institution_profile_from_dict():
    data = {
        "profileId": 1,
        "id": 10,
        "institutionCode": "ABC",
        "institutionName": "School A",
        "role": "guardian",
        "name": "John Doe",
        "profilePicture": {"url": "https://example.com/pic.jpg"},
        "shortName": "JD",
        "institutionRole": "parent",
        "metadata": "extra",
    }
    ip = InstitutionProfile.from_dict(data)
    assert ip.profile_id == 1
    assert ip.id == 10
    assert ip.institution_code == "ABC"
    assert ip.institution_name == "School A"
    assert ip.role == "guardian"
    assert ip.name == "John Doe"
    assert ip.profile_picture is not None
    assert ip.profile_picture.url == "https://example.com/pic.jpg"
    assert ip.short_name == "JD"
    assert ip.institution_role == "parent"
    assert ip.metadata == "extra"


def test_institution_profile_from_dict_minimal():
    data = {}
    ip = InstitutionProfile.from_dict(data)
    assert ip.profile_id is None
    assert ip.institution_name is None
    assert ip.profile_picture is None


def test_institution_profile_from_dict_empty_picture():
    data = {"profilePicture": {}}
    ip = InstitutionProfile.from_dict(data)
    assert ip.profile_picture is None


def test_institution_profile_creation():
    ip = InstitutionProfile(
        profile_id=1,
        institution_name="School",
        role="guardian",
    )
    assert ip.institution_name == "School"
    result = dict(ip)
    assert result["role"] == "guardian"
    assert "_raw" not in result
