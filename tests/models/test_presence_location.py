"""Tests for aula.models.presence_location."""

from aula.models.presence_location import PresenceLocation


def test_from_dict_full():
    data = {
        "id": 1234,
        "name": "Hal",
        "description": "Gymnastiksalen",
        "symbol": "icon-Aula_sfo_gymnastic_hall",
        "weekDayMask": None,
    }
    location = PresenceLocation.from_dict(data)
    assert location.id == 1234
    assert location.name == "Hal"
    assert location.description == "Gymnastiksalen"
    assert location.symbol == "icon-Aula_sfo_gymnastic_hall"
    assert location._raw is data


def test_from_dict_missing_optional():
    location = PresenceLocation.from_dict({"name": "Ude"})
    assert location.id is None
    assert location.name == "Ude"
    assert location.description == ""
    assert location.symbol == ""


def test_from_dict_null_fields():
    """Aula sends explicit nulls rather than omitting keys."""
    location = PresenceLocation.from_dict({"id": None, "name": "Ude", "description": None})
    assert location.id is None
    assert location.description == ""


def test_from_dict_string_id_is_coerced():
    assert PresenceLocation.from_dict({"id": "99"}).id == 99


def test_from_dict_non_numeric_id_is_dropped(caplog):
    location = PresenceLocation.from_dict({"id": "abc", "name": "Ude"})
    assert location.id is None
    assert location.name == "Ude"
    assert "Non-numeric location id" in caplog.text


def test_parse_dict():
    location = PresenceLocation.parse({"id": 1, "name": "Ude"})
    assert location is not None
    assert location.name == "Ude"


def test_parse_none():
    assert PresenceLocation.parse(None) is None


def test_parse_string():
    location = PresenceLocation.parse("Room A")
    assert location is not None
    assert location.name == "Room A"
    assert location._raw is None


def test_parse_empty_string():
    assert PresenceLocation.parse("") is None


def test_parse_unexpected_type(caplog):
    assert PresenceLocation.parse(42) is None
    assert "Unexpected location value" in caplog.text


def test_dict_conversion_excludes_raw():
    location = PresenceLocation.from_dict({"id": 1, "name": "Ude"})
    result = dict(location)
    assert result == {"id": 1, "name": "Ude", "description": "", "symbol": ""}
    assert "_raw" not in result
