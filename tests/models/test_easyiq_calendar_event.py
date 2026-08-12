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
    # Empty rather than a placeholder: rendering decides how to show it.
    assert event.title == ""


def test_item_type_accepts_a_string():
    """EasyIQ has returned the type as a number and as a string."""
    assert EasyIQCalendarEvent.from_dict({"itemType": "4"}).item_type == 4
    assert EasyIQCalendarEvent.from_dict({"itemType": "not-a-number"}).item_type is None


def test_pascal_case_keys_are_read():
    """EasyIQ's homework controller answers in PascalCase, the calendar one does not."""
    event = EasyIQCalendarEvent.from_dict(
        {
            "ItemType": 4,
            "Start": "2026-02-28T00:00:00",
            "End": "2026-02-28T09:00:00",
            "Courses": "Dansk",
            "Activities": "Læselektie",
            "Description": "<p>Side 40</p>",
        }
    )
    assert event.item_type == 4
    assert event.start == "2026-02-28T00:00:00"
    assert event.end == "2026-02-28T09:00:00"
    assert event.courses == "Dansk"
    assert event.activities == "Læselektie"
    assert event.description == "<p>Side 40</p>"


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


def test_item_types_match_the_widget_source():
    """The homework widget filters on 1, 2, 3, 4 and 8 (CalendarItem.js)."""
    assert set(HOMEWORK_ITEM_TYPES) == {1, 2, 3, 4, 8}
    assert set(WEEKPLAN_ITEM_TYPES) == {8, 9}
    # 8 is VigtigInformation, which both views show.
    assert set(WEEKPLAN_ITEM_TYPES) & set(HOMEWORK_ITEM_TYPES) == {8}


def test_html_entities_are_unescaped():
    """The portal sends entities in its text, unlike other Aula sources."""
    event = EasyIQCalendarEvent.from_dict(
        {"Description": "skal v&aelig;re l&aelig;st", "CoursesDisplay": "Dansk &amp; Historie"}
    )
    assert event.description == "skal være læst"
    assert event.courses == "Dansk & Historie"


def test_whitespace_only_title_falls_through():
    """The portal pads unused titles with a single space."""
    event = EasyIQCalendarEvent.from_dict({"Title": " ", "Activities": "Læsebånd"})
    assert event.courses == ""
    assert event.title == "Læsebånd"


def test_iso_timestamp_is_preferred_over_the_display_string():
    event = EasyIQCalendarEvent.from_dict(
        {"StartTimeISO": "2026-08-18T08:00:00", "Start": "2026/08/18 08:00"}
    )
    assert event.start == "2026-08-18T08:00:00"


def test_event_id_is_read():
    assert EasyIQCalendarEvent.from_dict({"Id": 17363414}).event_id == "17363414"


def test_dict_conversion_drops_raw():
    result = dict(EasyIQCalendarEvent.from_dict({"itemType": 4, "courses": "Dansk"}))
    assert result["courses"] == "Dansk"
    assert "_raw" not in result
