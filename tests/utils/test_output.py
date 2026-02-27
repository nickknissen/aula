"""Tests for aula.utils.output."""

import datetime

from aula.models.notification import Notification
from aula.utils.output import (
    clip,
    format_calendar_context_lines,
    format_heading_lines,
    format_message_lines,
    format_notification_lines,
    format_post_lines,
    format_record_lines,
    format_report_intro_lines,
    format_row,
)


class TestFormatHeadingLines:
    def test_returns_title_and_underline(self):
        assert format_heading_lines("Overview") == ["Overview", "========"]

    def test_strips_whitespace(self):
        assert format_heading_lines("  Profile  ") == ["Profile", "======="]


class TestClip:
    def test_returns_text_when_within_limit(self):
        assert clip("abc", max_len=3) == "abc"

    def test_truncates_with_ellipsis(self):
        assert clip("abcdefgh", max_len=6) == "abc..."

    def test_handles_small_limits(self):
        assert clip("abcdef", max_len=2) == ".."


class TestFormatRow:
    def test_primary_only(self):
        assert format_row("Title") == "Title"

    def test_joins_non_empty_parts(self):
        assert format_row("Title", "meta", "detail") == "Title | meta | detail"

    def test_ignores_blank_parts(self):
        assert format_row("Title", "", "  ") == "Title"


class TestFormatNotificationLines:
    def test_formats_notification_as_structured_block(self):
        item = Notification(
            id="42",
            title="This is a notification title",
            module="inbox",
            event_type="new_message",
            notification_type="message",
            institution_code="1234",
            created_at="2026-02-27T10:00:00Z",
            expires_at="2026-03-01T00:00:00Z",
            related_child_name="Ada",
            post_id=77,
            album_id=None,
            media_id=88,
            is_read=False,
        )

        lines = format_notification_lines(item, institution_names={"1234": "Sunrise School"})

        assert lines == [
            "This is a notification title",
            "  Status: Unread",
            "  Module: inbox",
            "  Event: new_message",
            "  Type: message",
            "  Triggered: 2026-02-27T10:00:00Z",
            "  Expires: 2026-03-01T00:00:00Z",
            "  Institution: Sunrise School",
            "  Child: Ada",
            "  Post: 77",
            "  Media: 88",
        ]

    def test_hides_unknown_read_state(self):
        item = Notification(id="1", title="Hello", is_read=None)

        lines = format_notification_lines(item)

        assert lines[0] == "Hello"

    def test_falls_back_to_institution_code_when_name_missing(self):
        item = Notification(id="7", title="Hello", institution_code="999")

        lines = format_notification_lines(item, institution_names={"123": "Other School"})

        assert "  Institution: 999" in lines

    def test_hides_unknown_module_value(self):
        item = Notification(id="9", title="Title", module=None)

        lines = format_notification_lines(item)

        assert all("Module:" not in line for line in lines)


class TestFormatMessageLines:
    def test_formats_message_title_then_indented_details(self):
        lines = format_message_lines(
            title="Subject",
            sender="Teacher",
            send_date="2026-02-27",
            content="Line 1\nLine 2",
        )

        assert lines == [
            "Subject",
            "  Author: Teacher",
            "  Date: 2026-02-27",
            "  Body:",
            "  Line 1",
            "  Line 2",
        ]

    def test_falls_back_to_no_subject_and_empty_body_marker(self):
        lines = format_message_lines(
            title="",
            sender="Teacher",
            send_date="",
            content="",
        )

        assert lines == [
            "(No subject)",
            "  Author: Teacher",
            "  Body:",
            "  (no message body)",
        ]

    def test_uses_fallback_title_when_subject_missing(self):
        lines = format_message_lines(
            title="",
            sender="Teacher",
            send_date="2026-03-01",
            content="Body",
            fallback_title="For\u00e6ldrekaffe fredag d. 6 marts",
        )

        assert lines[0] == "For\u00e6ldrekaffe fredag d. 6 marts"

    def test_can_omit_title_line(self):
        lines = format_message_lines(
            title="Subject",
            sender="Teacher",
            send_date="2026-03-01",
            content="Body",
            include_title=False,
        )

        assert lines == [
            "  Author: Teacher",
            "  Date: 2026-03-01",
            "  Body:",
            "  Body",
        ]


class TestFormatPostLines:
    def test_formats_post_with_metadata_and_body(self):
        lines = format_post_lines(
            title="School trip",
            author="Class Teacher",
            date="2026-03-02 08:30",
            body="Bring lunch\nWear boots",
            attachments_count=2,
        )

        assert lines == [
            "School trip",
            "  Author: Class Teacher",
            "  Date: 2026-03-02 08:30",
            "  Body:",
            "  Bring lunch",
            "  Wear boots",
            "  Attachments: 2",
        ]

    def test_omits_empty_optional_fields(self):
        lines = format_post_lines(
            title="Title",
            author="",
            date="",
            body="",
            attachments_count=0,
        )

        assert lines == [
            "Title",
            "  Body:",
            "  (no post body)",
        ]


class TestFormatCalendarContextLines:
    def test_formats_calendar_context_lines(self):
        lines = format_calendar_context_lines(
            datetime.datetime(2026, 3, 1),
            datetime.datetime(2026, 3, 7),
            profile_count=2,
        )

        assert lines == [
            "  Start: 2026-03-01",
            "  End: 2026-03-07",
            "  Profiles: 2",
        ]


class TestFormatRecordLines:
    def test_formats_record_with_properties_and_body(self):
        lines = format_record_lines(
            title="Task title",
            properties=[("Student", "Ada"), ("Type", "Homework")],
            body_lines=["Read chapter 2", "Solve 3 questions"],
            body_label="Body",
        )

        assert lines == [
            "Task title",
            "  Student: Ada",
            "  Type: Homework",
            "  Body:",
            "  Read chapter 2",
            "  Solve 3 questions",
        ]

    def test_omits_empty_values_and_handles_empty_body(self):
        lines = format_record_lines(
            title="Task title",
            properties=[("Student", ""), ("Type", "Homework")],
            body_lines=[],
            body_label="Body",
            empty_body_text="(no body)",
        )

        assert lines == [
            "Task title",
            "  Type: Homework",
            "  Body:",
            "  (no body)",
        ]


class TestFormatReportIntroLines:
    def test_formats_report_intro(self):
        lines = format_report_intro_lines(
            title="Weekly overview",
            properties=[("Generated", "2026-03-02"), ("Period", "Mon-Fri")],
        )

        assert lines == [
            "Weekly overview",
            "  Generated: 2026-03-02",
            "  Period: Mon-Fri",
        ]
