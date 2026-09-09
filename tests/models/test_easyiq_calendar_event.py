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


def test_start_date_and_end_date_are_normalized():
    event = EasyIQCalendarEvent.from_dict(
        {"StartDate": "2026/08/13 12:55", "EndDate": "2026/08/13 14:25"}
    )
    assert event.start == "2026-08-13T12:55:00"
    assert event.end == "2026-08-13T14:25:00"


def test_owner_name_aliases_are_read():
    assert EasyIQCalendarEvent.from_dict({"OwnerName": "Ada Teacher"}).owner_name == "Ada Teacher"
    assert EasyIQCalendarEvent.from_dict({"teacher": "Grace Teacher"}).owner_name == "Grace Teacher"


def test_is_all_day_uses_only_known_true_encodings():
    for value in (True, "true", "1", "yes", 1):
        event = EasyIQCalendarEvent.from_dict({"CoursesDisplay": "Dansk", "IsAllDay": value})
        assert event.is_all_day is True

    for value in (False, "false", "0", 0, "sometimes", None):
        event = EasyIQCalendarEvent.from_dict({"CoursesDisplay": "Dansk", "IsAllDay": value})
        assert event.is_all_day is False

    assert EasyIQCalendarEvent.from_dict({"CoursesDisplay": "Dansk"}).is_all_day is False


def test_rows_without_a_course_are_all_day_notices():
    notice = EasyIQCalendarEvent.from_dict({"Description": "School closed"})
    lesson = EasyIQCalendarEvent.from_dict({"CoursesDisplay": "Matematik"})

    assert notice.is_notice is True
    assert notice.is_all_day is True
    assert lesson.is_notice is False


def test_explicit_title_does_not_pretend_to_be_a_course():
    event = EasyIQCalendarEvent.from_dict({"Title": "Sports day"})

    assert event.event_title == "Sports day"
    assert event.title == "Sports day"
    assert event.courses == ""
    assert event.is_notice is True
    assert EasyIQCalendarEvent.from_dict({"Name": "Parents evening"}).event_title == (
        "Parents evening"
    )


def test_notice_title_comes_from_heading_then_visible_text():
    with_heading = EasyIQCalendarEvent.from_dict(
        {"Description": "<h1> </h1><p>Introduction</p><h2>School &amp; SFO closed</h2>"}
    )
    without_heading = EasyIQCalendarEvent.from_dict(
        {"Description": "<p>Remember indoor shoes</p><p>Applies all week</p>"}
    )

    assert with_heading.title == "School & SFO closed"
    assert without_heading.title == "Remember indoor shoes"


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


def test_start_and_end_share_a_format_when_only_one_has_an_iso_field():
    """EndTimeISO is null on rows where StartTimeISO is set."""
    event = EasyIQCalendarEvent.from_dict(
        {
            "StartTimeISO": "2026-08-13T12:55:00.0000000",
            "EndTimeISO": None,
            "Start": "2026/08/13 12:55",
            "End": "2026/08/13 14:25",
        }
    )
    assert event.start == "2026-08-13T12:55:00"
    assert event.end == "2026-08-13T14:25:00"


def test_seconds_in_the_display_format_are_kept():
    event = EasyIQCalendarEvent.from_dict({"Start": "2026/08/13 12:55:30"})
    assert event.start == "2026-08-13T12:55:30"


def test_an_unparseable_timestamp_is_passed_through():
    event = EasyIQCalendarEvent.from_dict({"Start": "next tuesday"})
    assert event.start == "next tuesday"


def test_event_id_is_read():
    assert EasyIQCalendarEvent.from_dict({"Id": 17363414}).event_id == "17363414"


def test_dict_conversion_drops_raw():
    result = dict(
        EasyIQCalendarEvent.from_dict(
            {"itemType": 4, "courses": "Dansk", "OwnerName": "Ada Teacher", "IsAllDay": True}
        )
    )
    assert result["courses"] == "Dansk"
    assert result["owner_name"] == "Ada Teacher"
    assert result["is_all_day"] is True
    assert result["is_notice"] is False
    assert "_raw" not in result
