"""The data-building halves of the CLI commands, called without Click."""

import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from aula.cli._helpers import _event_slot_lines
from aula.cli.daily_summary import build_daily_summary
from aula.cli.presence import PresenceNow, current_plan, fetch_presence_now
from aula.cli.weekly_summary import WeeklySummaryProvider, build_weekly_summary, week_bounds
from aula.models import CalendarEvent, Child, DailyOverview, DayTemplate, MUTask, Profile
from aula.models.pickup_responsible import ChildPickupResponsibles
from aula.widgets import EasyIQChildNotInPortal

TZ = ZoneInfo("Europe/Copenhagen")
MONDAY = datetime.datetime(2026, 11, 23, tzinfo=TZ)


def _child(child_id: int, user_id: str | None = None) -> Child:
    return Child(
        id=child_id,
        profile_id=child_id + 1000,
        name=f"Barn {child_id}",
        institution_name="Skole",
        profile_picture="",
        user_id=user_id or f"barn{child_id}",
        institution_code="100",
    )


def _event(title: str, start_hour: int) -> CalendarEvent:
    return CalendarEvent(
        id=start_hour,
        title=title,
        start_datetime=MONDAY.replace(hour=start_hour),
        end_datetime=MONDAY.replace(hour=start_hour + 1),
        teacher_name=None,
        has_substitute=False,
        substitute_name=None,
        location=None,
        belongs_to=None,
    )


def _client(children: list[Child]) -> MagicMock:
    client = MagicMock()
    client.get_calendar_events = AsyncMock(return_value=[])
    client.get_message_threads = AsyncMock(return_value=[])
    client.get_profile_context = AsyncMock(return_value={"data": {"userId": "guardian"}})
    client.get_widgets = AsyncMock(return_value=[])
    client.widgets = MagicMock()
    client.profile = Profile(profile_id=1, display_name="Værge", children=children)
    return client


def test_event_slot_lines_merge_events_that_share_a_timeslot():
    lines = _event_slot_lines([_event("Musik", 10), _event("Dansk", 8), _event("Matematik", 8)])

    assert lines == ["- 08:00–09:00  Dansk / Matematik", "- 10:00–11:00  Musik"]


def test_week_bounds_run_from_monday_to_friday_night():
    start, end = week_bounds("2026-W48")

    assert (start, end) == (MONDAY, datetime.datetime(2026, 11, 27, 23, 59, 59, tzinfo=TZ))


class TestBuildWeeklySummary:
    @pytest.mark.asyncio
    async def test_providers_that_were_not_enabled_stay_none(self):
        children = [_child(1)]
        client = _client(children)

        summary = await build_weekly_summary(
            client,
            client.profile,
            children,
            "2026-W48",
            set(),
            only_selected_children=False,
            with_thread_messages=True,
        )

        assert summary.mu_tasks is None
        assert summary.easyiq_weekplan is None
        client.get_profile_context.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_child_easyiq_does_not_know_is_left_out(self):
        children = [_child(1), _child(2)]
        client = _client(children)

        async def weekplan(*args, child_profile_id, **kwargs):
            if child_profile_id == "2":
                raise EasyIQChildNotInPortal("unknown child")
            return [MagicMock()]

        client.widgets.get_easyiq_weekplan = AsyncMock(side_effect=weekplan)
        client.get_widgets = AsyncMock(return_value=[MagicMock(widget_id="0128")])

        summary = await build_weekly_summary(
            client,
            client.profile,
            children,
            "2026-W48",
            {WeeklySummaryProvider.EASYIQ},
            only_selected_children=False,
            with_thread_messages=False,
        )

        assert [c.id for c, _ in summary.easyiq_weekplan] == [1]

    @pytest.mark.asyncio
    async def test_widget_context_failure_is_kept_for_the_command_to_report(self):
        children = [_child(1)]
        client = _client(children)
        client.get_profile_context = AsyncMock(return_value={"data": {}})

        summary = await build_weekly_summary(
            client,
            client.profile,
            children,
            "2026-W48",
            set(WeeklySummaryProvider),
            only_selected_children=False,
            with_thread_messages=False,
        )

        assert (
            summary.widget_error == "The profile context does not name the guardian (data.userId)"
        )
        assert summary.mu_tasks is None


class TestBuildDailySummary:
    @pytest.mark.asyncio
    async def test_overview_is_only_fetched_for_today(self):
        children = [_child(1)]
        client = _client(children)
        client.get_presence_templates = AsyncMock(return_value=[])
        client.get_daily_overview = AsyncMock(return_value=DailyOverview(id=1))

        summary = await build_daily_summary(
            client,
            client.profile,
            children,
            MONDAY,
            is_today=False,
            only_selected_children=False,
            with_thread_messages=False,
        )

        client.get_daily_overview.assert_not_awaited()
        assert summary.children[0].overview is None

    @pytest.mark.asyncio
    async def test_only_tasks_due_that_day_are_kept(self):
        children = [_child(1)]
        client = _client(children)
        client.get_presence_templates = AsyncMock(return_value=[])
        client.get_widgets = AsyncMock(return_value=[MagicMock(widget_id="0030")])

        def task(title, weekday, due=None):
            return MUTask(
                id=title,
                title=title,
                task_type="",
                due_date=due,
                weekday=weekday,
                week_number=48,
                is_completed=False,
                student_name="",
                unilogin="",
                url="",
            )

        client.widgets.get_mu_tasks = AsyncMock(
            return_value=[
                task("mandag", "Mandag"),
                task("dato", "", MONDAY),
                task("tirsdag", "Tirsdag"),
            ]
        )

        summary = await build_daily_summary(
            client,
            client.profile,
            children,
            MONDAY,
            is_today=False,
            only_selected_children=False,
            with_thread_messages=False,
        )

        assert [t.title for t in summary.tasks_due] == ["mandag", "dato"]


class TestPresence:
    def test_the_days_template_wins_over_the_overview(self):
        now = PresenceNow(
            overviews={1: DailyOverview(entry_time="08:00", exit_time="15:00", exit_with="Far")},
            templates={1: DayTemplate(id=7, exit_time="14:00")},
            pickup_names=[],
        )

        plan = current_plan(now, 1)

        assert (plan.entry_time, plan.exit_time, plan.exit_with, plan.template_id) == (
            "08:00",
            "14:00",
            "Far",
            7,
        )

    @pytest.mark.asyncio
    async def test_pickup_names_are_listed_once_across_children(self):
        person = {"name": "Værge Et", "relation": "Far"}
        client = MagicMock()
        client.get_daily_overview = AsyncMock(return_value=None)
        client.get_presence_templates = AsyncMock(return_value=[])
        client.get_pickup_responsibles = AsyncMock(
            return_value=[
                ChildPickupResponsibles.from_dict({"uniStudentId": 1, "relatedPersons": [person]}),
                ChildPickupResponsibles.from_dict(
                    {
                        "uniStudentId": 2,
                        "relatedPersons": [person],
                        "pickupSuggestions": [{"pickUpName": "Bedste", "id": 3}],
                    }
                ),
            ]
        )

        now = await fetch_presence_now(client, [_child(1), _child(2)], MONDAY.date())

        assert now.pickup_names == ["Værge Et (Far)", "Bedste"]
