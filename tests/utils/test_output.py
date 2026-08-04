"""Tests for aula.utils.output."""

import datetime

from aula.models.notification import Notification
from aula.utils.output import (
    ContactRow,
    build_contact_rows,
    build_contact_table,
    clip,
    format_calendar_context_lines,
    format_heading_lines,
    format_message_lines,
    format_notification_lines,
    format_post_lines,
    format_record_lines,
    format_report_intro_lines,
    format_row,
    scope_relations_to_children,
    sort_contact_rows,
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


def _address(street: str, postal_code: object = None, district: str | None = None) -> dict:
    return {"street": street, "postalCode": postal_code, "postalDistrict": district}


class TestBuildContactRows:
    def test_child_pairs_with_each_guardian(self):
        item = {
            "fullName": "Barn Et",
            "role": "child",
            "metadata": "3.1",
            "relations": [
                {
                    "fullName": "Værge Far",
                    "role": "guardian",
                    "relation": "Far",
                    "mobilePhoneNumber": "10000001",
                    "address": _address("Testvej 1", 1000, "Testby"),
                },
                {
                    "fullName": "Værge Mor",
                    "role": "guardian",
                    "relation": "Mor",
                    "mobilePhoneNumber": "10000002",
                    "address": _address("Testvej 2", 1000, "Testby"),
                },
            ],
        }
        assert build_contact_rows(item) == [
            ContactRow(
                child="Barn Et",
                guardian="Værge Far",
                relation="Far",
                class_name="3.1",
                phone="10000001",
                address="Testvej 1, 1000 Testby",
            ),
            ContactRow(
                child="Barn Et",
                guardian="Værge Mor",
                relation="Mor",
                class_name="3.1",
                phone="10000002",
                address="Testvej 2, 1000 Testby",
            ),
        ]

    def test_guardian_details_come_from_the_guardian_not_the_child(self):
        """A child relation carries its own phone/address; the guardian's must win."""
        item = {
            "fullName": "Værge Et",
            "role": "guardian",
            "mobilePhoneNumber": "10000001",
            "address": _address("Værgevej 1", 1000, "Testby"),
            "relations": [
                {
                    "fullName": "Barn Et",
                    "role": "child",
                    "relation": "Far",
                    "metadata": "3.1",
                    "mobilePhoneNumber": "20000002",
                    "address": _address("Barnevej 2", 2000, "Andenby"),
                },
            ],
        }
        assert build_contact_rows(item) == [
            ContactRow(
                child="Barn Et",
                guardian="Værge Et",
                relation="Far",
                class_name="3.1",
                phone="10000001",
                address="Værgevej 1, 1000 Testby",
            )
        ]

    def test_phone_falls_back_from_mobile_to_home_to_work(self):
        base = {"fullName": "Barn Et", "role": "child", "relations": []}
        assert build_contact_rows({**base, "mobilePhoneNumber": "1"})[0].phone == "1"
        assert build_contact_rows({**base, "homePhoneNumber": "2"})[0].phone == "2"
        assert build_contact_rows({**base, "workPhoneNumber": "3"})[0].phone == "3"

    def test_blank_phone_values_are_skipped(self):
        item = {
            "fullName": "Barn Et",
            "role": "child",
            "relations": [],
            "mobilePhoneNumber": "",
            "homePhoneNumber": None,
            "workPhoneNumber": "10000003",
        }
        assert build_contact_rows(item)[0].phone == "10000003"

    def test_address_omits_missing_parts(self):
        def address_for(address):
            item = {"fullName": "Barn Et", "role": "child", "relations": [], "address": address}
            return build_contact_rows(item)[0].address

        assert address_for(_address("Ukendt")) == "Ukendt"
        assert address_for(_address("Testvej 1", 1000)) == "Testvej 1, 1000"
        assert address_for(_address("", 1000, "Testby")) == "1000 Testby"
        assert address_for(None) == ""

    def test_relations_of_the_wrong_role_are_ignored(self):
        item = {
            "fullName": "Barn Et",
            "role": "child",
            "relations": [{"fullName": "Barn To", "role": "child"}],
        }
        assert build_contact_rows(item) == [ContactRow("Barn Et", "", "child", "", "", "")]

    def test_employee_falls_back_to_name_and_role(self):
        item = {"fullName": "Ansat Et", "role": "employee", "relations": [], "metadata": "Lærer"}
        assert build_contact_rows(item) == [ContactRow("Ansat Et", "", "employee", "Lærer", "", "")]

    def test_guardian_without_relations_falls_back(self):
        item = {"fullName": "Værge Et", "role": "guardian", "relations": None}
        assert build_contact_rows(item) == [ContactRow("Værge Et", "", "guardian", "", "", "")]

    def test_missing_relation_label_is_empty(self):
        item = {
            "fullName": "Barn Et",
            "role": "child",
            "relations": [{"fullName": "Værge Et", "role": "guardian"}],
        }
        assert build_contact_rows(item) == [ContactRow("Barn Et", "Værge Et", "", "", "", "")]

    def test_non_dict_relations_are_skipped(self):
        item = {"fullName": "Barn Et", "role": "child", "relations": ["nope", None]}
        assert build_contact_rows(item) == [ContactRow("Barn Et", "", "child", "", "", "")]

    def test_unknown_name_fallback(self):
        assert build_contact_rows({"role": "employee"}) == [
            ContactRow("Unknown", "", "employee", "", "", "")
        ]


class TestBuildContactTable:
    def test_paired_listing_uses_child_guardian_columns(self):
        contacts = [
            {
                "fullName": "Barn Et",
                "role": "child",
                "metadata": "3.1",
                "relations": [{"fullName": "Værge Et", "role": "guardian", "relation": "Far"}],
            }
        ]

        headers, rows = build_contact_table(contacts)

        assert headers == ["Child", "Guardian", "Relation", "Class", "Phone", "Address"]
        assert rows == [("Barn Et", "Værge Et", "Far", "3.1", "", "")]

    def test_flat_listing_drops_the_empty_guardian_column(self):
        contacts = [
            {"fullName": "Ansat Et", "role": "employee", "metadata": "Lærer", "relations": []},
        ]

        headers, rows = build_contact_table(contacts)

        assert headers == ["Name", "Role", "Details", "Phone", "Address"]
        assert rows == [("Ansat Et", "employee", "Lærer", "", "")]

    def test_rows_are_sorted_child_then_guardian(self):
        contacts = [
            {
                "fullName": "Barn Bo",
                "role": "child",
                "relations": [{"fullName": "Værge Zeta", "role": "guardian"}],
            },
            {
                "fullName": "Barn Ada",
                "role": "child",
                "relations": [
                    {"fullName": "Værge Bent", "role": "guardian"},
                    {"fullName": "Værge Anne", "role": "guardian"},
                ],
            },
        ]

        _, rows = build_contact_table(contacts)

        assert [(row[0], row[1]) for row in rows] == [
            ("Barn Ada", "Værge Anne"),
            ("Barn Ada", "Værge Bent"),
            ("Barn Bo", "Værge Zeta"),
        ]

    def test_every_row_matches_the_header_width(self):
        contacts = [
            {
                "fullName": "Barn Et",
                "role": "child",
                "relations": [{"fullName": "Værge Et", "role": "guardian"}],
            }
        ]

        headers, rows = build_contact_table(contacts)

        assert all(len(row) == len(headers) for row in rows)

    def test_empty_input(self):
        headers, rows = build_contact_table([])

        assert rows == []
        assert headers == ["Name", "Role", "Details", "Phone", "Address"]


def _row(child: str, guardian: str = "g") -> ContactRow:
    return ContactRow(child, guardian, "", "", "", "")


class TestSortContactRows:
    def test_sorts_by_child_then_guardian(self):
        rows = [_row("Bo", "Zeta"), _row("Ada", "Bent"), _row("Bo", "Alma"), _row("Ada", "Anne")]

        assert [(r.child, r.guardian) for r in sort_contact_rows(rows)] == [
            ("Ada", "Anne"),
            ("Ada", "Bent"),
            ("Bo", "Alma"),
            ("Bo", "Zeta"),
        ]

    def test_sort_is_case_insensitive(self):
        rows = [_row("bob"), _row("Alice")]

        assert [r.child for r in sort_contact_rows(rows)] == ["Alice", "bob"]

    def test_danish_letters_sort_after_z_in_danish_order(self):
        rows = [_row(name) for name in ["Åge", "Bo", "Æbbe", "Øjvind", "Zenia"]]

        assert [r.child for r in sort_contact_rows(rows)] == [
            "Bo",
            "Zenia",
            "Æbbe",
            "Øjvind",
            "Åge",
        ]

    def test_does_not_mutate_the_input(self):
        rows = [_row("Bo"), _row("Ada")]

        sort_contact_rows(rows)

        assert rows[0].child == "Bo"


class TestScopeRelationsToChildren:
    GUARDIAN = {
        "fullName": "Værge Et",
        "role": "guardian",
        "relations": [
            {"fullName": "Barn I Gruppen", "role": "child", "id": 1, "metadata": "3.1"},
            {"fullName": "Søskende Udenfor", "role": "child", "id": 2, "metadata": "0.1"},
        ],
    }

    def test_drops_children_from_other_groups(self):
        scoped = scope_relations_to_children([self.GUARDIAN], [{"id": 1}])

        assert [r["fullName"] for r in scoped[0]["relations"]] == ["Barn I Gruppen"]

    def test_does_not_mutate_the_input(self):
        scope_relations_to_children([self.GUARDIAN], [{"id": 1}])

        assert len(self.GUARDIAN["relations"]) == 2

    def test_drops_guardians_with_no_child_in_the_group(self):
        assert scope_relations_to_children([self.GUARDIAN], [{"id": 999}]) == []

    def test_returns_input_unchanged_for_a_group_without_children(self):
        contacts = [self.GUARDIAN]

        assert scope_relations_to_children(contacts, []) is contacts

    def test_ignores_group_children_without_ids(self):
        contacts = [self.GUARDIAN]

        assert scope_relations_to_children(contacts, [{"fullName": "no id"}]) is contacts

    def test_keeps_non_child_relations(self):
        item = {
            "fullName": "Værge Et",
            "role": "guardian",
            "relations": [
                {"fullName": "Barn I Gruppen", "role": "child", "id": 1},
                {"fullName": "Medværge", "role": "guardian", "id": 77},
            ],
        }

        scoped = scope_relations_to_children([item], [{"id": 1}])

        assert [r["fullName"] for r in scoped[0]["relations"]] == ["Barn I Gruppen", "Medværge"]

    def test_keeps_contacts_that_never_had_child_relations(self):
        item = {"fullName": "Ansat Et", "role": "employee", "relations": []}

        assert scope_relations_to_children([item], [{"id": 1}]) == [item]


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
        )

        lines = format_notification_lines(item, institution_names={"1234": "Sunrise School"})

        assert lines == [
            "This is a notification title",
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
