"""Tests for aula.utils.week."""

from aula.utils.week import DANISH_WEEKDAYS, monday_of_week, weekday_index


class TestMondayOfWeek:
    def test_returns_monday_of_iso_week(self):
        assert monday_of_week("2026-W34") == "2026-08-17T00:00:00Z"

    def test_falls_back_to_today_on_bad_input(self):
        assert monday_of_week("nonsense").endswith("T00:00:00Z")


class TestWeekdayIndex:
    def test_known_days_are_monday_first(self):
        assert weekday_index("Mandag") == 0
        assert weekday_index("Søndag") == 6

    def test_case_and_padding_are_ignored(self):
        assert weekday_index(" tirsdag ") == 1

    def test_unknown_and_missing_sort_last(self):
        assert weekday_index("Someday") == len(DANISH_WEEKDAYS)
        assert weekday_index("") == len(DANISH_WEEKDAYS)
        assert weekday_index(None) == len(DANISH_WEEKDAYS)
