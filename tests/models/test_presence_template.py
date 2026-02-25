"""Tests for aula.models.presence_template."""

from aula.models.presence_template import (
    DayTemplate,
    PresenceWeekTemplate,
    SpareTimeActivity,
)


class TestSpareTimeActivity:
    """Tests for SpareTimeActivity model."""

    def test_spare_time_activity_from_dict_full(self):
        """Test parsing full spare time activity data."""
        data = {
            "startTime": "15:00",
            "endTime": "17:00",
            "comment": "After-school care",
        }
        activity = SpareTimeActivity.from_dict(data)
        assert activity.start_time == "15:00"
        assert activity.end_time == "17:00"
        assert activity.comment == "After-school care"
        assert activity._raw is data

    def test_spare_time_activity_from_dict_minimal(self):
        """Test parsing spare time activity with minimal data."""
        data = {}
        activity = SpareTimeActivity.from_dict(data)
        assert activity.start_time is None
        assert activity.end_time is None
        assert activity.comment is None
        assert activity._raw is data

    def test_spare_time_activity_from_dict_partial(self):
        """Test parsing spare time activity with partial data."""
        data = {
            "startTime": "14:30",
            "comment": "Pick up at playground",
        }
        activity = SpareTimeActivity.from_dict(data)
        assert activity.start_time == "14:30"
        assert activity.end_time is None
        assert activity.comment == "Pick up at playground"

    def test_spare_time_activity_dict_conversion(self):
        """Test dict conversion of spare time activity."""
        activity = SpareTimeActivity(
            start_time="15:00",
            end_time="17:00",
            comment="Activity",
        )
        result = dict(activity)
        assert result["start_time"] == "15:00"
        assert result["end_time"] == "17:00"
        assert result["comment"] == "Activity"
        assert "_raw" not in result


class TestDayTemplate:
    """Tests for DayTemplate model."""

    def test_day_template_from_dict_full(self):
        """Test parsing full day template data."""
        data = {
            "id": 123,
            "dayOfWeek": 1,
            "byDate": "2026-02-25",
            "repeatPattern": "WEEKLY",
            "repeatFromDate": "2026-02-01",
            "repeatToDate": "2026-12-31",
            "isOnVacation": False,
            "activityType": 1,
            "entryTime": "08:00",
            "exitTime": "16:00",
            "exitWith": "Parent",
            "comment": "Regular day",
            "spareTimeActivity": {
                "startTime": "15:00",
                "endTime": "17:00",
                "comment": "After-school care",
            },
        }
        day = DayTemplate.from_dict(data)
        assert day.id == 123
        assert day.day_of_week == 1
        assert day.by_date == "2026-02-25"
        assert day.repeat_pattern == "WEEKLY"
        assert day.repeat_from_date == "2026-02-01"
        assert day.repeat_to_date == "2026-12-31"
        assert day.is_on_vacation is False
        assert day.activity_type == 1
        assert day.entry_time == "08:00"
        assert day.exit_time == "16:00"
        assert day.exit_with == "Parent"
        assert day.comment == "Regular day"
        assert day.spare_time_activity is not None
        assert day.spare_time_activity.start_time == "15:00"
        assert day.spare_time_activity.end_time == "17:00"
        assert day._raw is data

    def test_day_template_from_dict_minimal(self):
        """Test parsing day template with minimal data."""
        data = {}
        day = DayTemplate.from_dict(data)
        assert day.id is None
        assert day.day_of_week is None
        assert day.by_date is None
        assert day.entry_time is None
        assert day.exit_time is None
        assert day.spare_time_activity is None
        assert day.is_on_vacation is False

    def test_day_template_from_dict_no_spare_time(self):
        """Test parsing day template without spare time activity."""
        data = {
            "id": 1,
            "byDate": "2026-02-25",
            "entryTime": "08:00",
            "exitTime": "16:00",
        }
        day = DayTemplate.from_dict(data)
        assert day.id == 1
        assert day.entry_time == "08:00"
        assert day.spare_time_activity is None

    def test_day_template_from_dict_empty_spare_time(self):
        """Test parsing day template with empty spare time activity dict (falsy, skipped)."""
        data = {
            "id": 1,
            "byDate": "2026-02-25",
            "spareTimeActivity": {},
        }
        day = DayTemplate.from_dict(data)
        assert day.id == 1
        # Empty dict is falsy, so spare_time_activity is not created
        assert day.spare_time_activity is None

    def test_day_template_from_dict_vacation(self):
        """Test parsing day template with vacation flag."""
        data = {
            "id": 1,
            "byDate": "2026-02-25",
            "isOnVacation": True,
        }
        day = DayTemplate.from_dict(data)
        assert day.is_on_vacation is True

    def test_day_template_dict_conversion(self):
        """Test dict conversion of day template."""
        day = DayTemplate(
            id=1,
            by_date="2026-02-25",
            entry_time="08:00",
            exit_time="16:00",
        )
        result = dict(day)
        assert result["id"] == 1
        assert result["by_date"] == "2026-02-25"
        assert result["entry_time"] == "08:00"
        assert "_raw" not in result


class TestPresenceWeekTemplate:
    """Tests for PresenceWeekTemplate model."""

    def test_presence_week_template_from_dict_full(self):
        """Test parsing full presence week template."""
        data = {
            "institutionProfile": {
                "id": 10,
                "profileId": 99,
                "institutionName": "School",
                "role": "student",
            },
            "dayTemplates": [
                {
                    "id": 1,
                    "byDate": "2026-02-25",
                    "entryTime": "08:00",
                    "exitTime": "16:00",
                },
                {
                    "id": 2,
                    "byDate": "2026-02-26",
                    "entryTime": "08:00",
                    "exitTime": "16:00",
                },
            ],
        }
        template = PresenceWeekTemplate.from_dict(data)
        assert template.institution_profile is not None
        assert template.institution_profile.id == 10
        assert len(template.day_templates) == 2
        assert template.day_templates[0].by_date == "2026-02-25"
        assert template.day_templates[1].by_date == "2026-02-26"
        assert template._raw is data

    def test_presence_week_template_from_dict_minimal(self):
        """Test parsing presence week template with minimal data."""
        data = {}
        template = PresenceWeekTemplate.from_dict(data)
        assert template.institution_profile is None
        assert template.day_templates == []

    def test_presence_week_template_from_dict_no_institution(self):
        """Test parsing presence week template without institution profile."""
        data = {
            "dayTemplates": [
                {
                    "id": 1,
                    "byDate": "2026-02-25",
                    "entryTime": "08:00",
                },
            ],
        }
        template = PresenceWeekTemplate.from_dict(data)
        assert template.institution_profile is None
        assert len(template.day_templates) == 1

    def test_presence_week_template_from_dict_empty_day_templates(self):
        """Test parsing presence week template with empty day templates list."""
        data = {
            "institutionProfile": {
                "id": 10,
                "institutionName": "School",
            },
            "dayTemplates": [],
        }
        template = PresenceWeekTemplate.from_dict(data)
        assert template.institution_profile is not None
        assert template.day_templates == []

    def test_presence_week_template_from_dict_null_institution(self):
        """Test parsing presence week template with null institution profile."""
        data = {
            "institutionProfile": None,
            "dayTemplates": [
                {
                    "id": 1,
                    "byDate": "2026-02-25",
                },
            ],
        }
        template = PresenceWeekTemplate.from_dict(data)
        assert template.institution_profile is None
        assert len(template.day_templates) == 1

    def test_presence_week_template_dict_conversion(self):
        """Test dict conversion of presence week template."""
        template = PresenceWeekTemplate(
            institution_profile=None,
            day_templates=[],
        )
        result = dict(template)
        assert result["day_templates"] == []
        assert "_raw" not in result
