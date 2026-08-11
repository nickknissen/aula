"""Tests for aula.models.easyiq_calendar_event."""

from aula.models.easyiq_calendar_event import (
    HOMEWORK_ITEM_TYPES,
    WEEKPLAN_ITEM_TYPES,
    EasyIQCalendarEvent,
)


def test_from_dict_reads_the_primary_shape():
    data = {
        "itemType": 9,
        "start": "2026-02-24T08:00:00",
        "end": "2026-02-24T09:00:00",
        "courses": "Matematik",
        "activities": "Algebra",
        "description": "<p>Kapitel 3</p>",
    }
    event = EasyIQCalendarEvent.from_dict(data)
    assert event.item_type == 9
    assert event.start == "2026-02-24T08:00:00"
    assert event.end == "2026-02-24T09:00:00"
    assert event.courses == "Matematik"
    assert event.activities == "Algebra"
    assert event.description == "<p>Kapitel 3</p>"
    assert event._raw is data


def test_from_dict_defaults():
    event = EasyIQCalendarEvent.from_dict({})
    assert event.item_type is None
    assert event.start == ""
    assert event.title == "(untitled)"


def test_item_type_accepts_a_string():
    """EasyIQ has returned the type as a number and as a string."""
    assert EasyIQCalendarEvent.from_dict({"itemType": "4"}).item_type == 4
    assert EasyIQCalendarEvent.from_dict({"itemType": "not-a-number"}).item_type is None


def test_alternate_keys_are_read():
    event = EasyIQCalendarEvent.from_dict(
        {"type": 8, "startDateTime": "2026-02-24T08:00:00", "subject": "Idræt", "note": "Husk tøj"}
    )
    assert event.item_type == 8
    assert event.start == "2026-02-24T08:00:00"
    assert event.courses == "Idræt"
    assert event.description == "Husk tøj"


def test_list_values_are_joined():
    event = EasyIQCalendarEvent.from_dict({"activities": ["Læsning", "Skrivning"]})
    assert event.activities == "Læsning, Skrivning"


def test_title_falls_back_to_the_activity():
    assert EasyIQCalendarEvent.from_dict({"activities": "Læsebånd"}).title == "Læsebånd"


def test_item_types_do_not_overlap():
    assert not set(WEEKPLAN_ITEM_TYPES) & set(HOMEWORK_ITEM_TYPES)


def test_dict_conversion_drops_raw():
    result = dict(EasyIQCalendarEvent.from_dict({"itemType": 4, "courses": "Dansk"}))
    assert result["courses"] == "Dansk"
    assert "_raw" not in result
