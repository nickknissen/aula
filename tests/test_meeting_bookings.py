"""Synthetic calendar payloads exercise booking selection and request boundaries."""

import copy
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from click.testing import CliRunner

from aula.api_client import AulaApiClient
from aula.cli import meetings
from aula.http import HttpRequestError, HttpResponse
from aula.models import CalendarEvent, Child, Profile
from aula.models.meeting_booking import meeting_bookings, replace_booked_meetings


@pytest.fixture
def row():
    # The second interval is after a break. Arithmetic from the first start
    # would incorrectly turn a 09:40 appointment into a 09:20 appointment.
    return {
        "id": 42,
        "title": "Reading discussion",
        "type": "school_home_meeting",
        "startDateTime": "2026-11-02T09:00:00+01:00",
        "endDateTime": "2026-11-09T12:00:00+01:00",
        "primaryResource": {"name": "Room A"},
        "belongsToProfiles": [11, 12],
        "timeSlot": {
            "timeSlots": [
                {
                    "id": 99,
                    "timeSlotIndexes": [
                        {
                            "startTime": "2026-11-02T09:00:00+01:00",
                            "endTime": "2026-11-02T09:20:00+01:00",
                        },
                        {
                            "startTime": "2026-11-02T09:40:00+01:00",
                            "endTime": "2026-11-02T10:00:00+01:00",
                        },
                    ],
                    "answers": [
                        {"concerningProfileId": 11, "selectedTimeSlotIndex": 1},
                        {"concerningProfileId": 11, "selectedTimeSlotIndex": 1},
                        {"concerningProfileId": 12, "selectedTimeSlotIndex": 0},
                    ],
                }
            ]
        },
    }


def test_actual_interval_after_break_and_duplicate_guardian_answers(row):
    bookings = meeting_bookings([row, row], 11)
    assert len(bookings) == 1
    booking = bookings[0]
    assert booking.start_datetime.isoformat() == "2026-11-02T09:40:00+01:00"
    assert booking.end_datetime.isoformat() == "2026-11-02T10:00:00+01:00"
    assert booking.child_id == 11
    assert booking.meeting_id == 42
    assert booking.location == "Room A"
    assert "_raw" not in dict(booking)


def test_other_children_and_unbooked_invitations_are_excluded(row):
    assert meeting_bookings([row], 13) == []
    row["timeSlot"] = {"timeSlots": []}
    assert meeting_bookings([row], 11) == []
    row["timeSlot"] = {}
    assert meeting_bookings([row], 11) == []


def test_fixed_appointments_are_scoped_and_sorted(row):
    fixed = {
        **row,
        "id": 43,
        "timeSlot": None,
        "primaryResource": None,
        "primaryResourceText": "Office",
        "type": "parental_meeting",
    }
    bookings = meeting_bookings([row, fixed], 11)
    assert [b.meeting_id for b in bookings] == [43, 42]
    assert bookings[0].location == "Office"
    assert meeting_bookings([fixed], 13) == []


@pytest.mark.parametrize("index", [-1, 10, None, True, "1"])
def test_invalid_indexes_do_not_hide_a_valid_answer(row, index):
    row["timeSlot"]["timeSlots"][0]["answers"].insert(
        0, {"concerningProfileId": 11, "selectedTimeSlotIndex": index}
    )
    assert len(meeting_bookings([row], 11)) == 1


def test_invalid_interval_does_not_hide_another_booking(row):
    broken = copy.deepcopy(row)
    broken["id"] = 99
    broken["timeSlot"]["timeSlots"][0]["timeSlotIndexes"][1]["startTime"] = "bad"
    assert [b.meeting_id for b in meeting_bookings([broken, row], 11)] == [42]


@pytest.mark.parametrize("value", [None, {}, {"type": "lesson"}])
def test_nonmeeting_rows_are_ignored(value):
    assert meeting_bookings([value], 11) == []


@pytest.fixture
def client(row):
    api = AulaApiClient(http_client=AsyncMock())
    api._request_with_version_retry = AsyncMock(
        return_value=HttpResponse(status_code=200, data={"status": {"code": 0}, "data": [row]})
    )
    return api


@pytest.mark.asyncio
async def test_long_range_requests_are_contiguous_and_deduplicated(client):
    start = datetime(2026, 10, 1, tzinfo=ZoneInfo("Europe/Copenhagen"))
    end = start + timedelta(days=100)
    bookings = await client.get_meeting_bookings(11, start, end)
    calls = client._request_with_version_retry.await_args_list
    assert len(calls) == 3
    assert len(bookings) == 1
    previous_end = start
    for call in calls:
        assert call.args[0] == "post"
        assert "calendar.getEventsByProfileIdsAndResourceIds" in call.args[1]
        payload = call.kwargs["json"]
        beginning = datetime.strptime(payload["start"], "%Y-%m-%d %H:%M:%S.%f%z")
        ending = datetime.strptime(payload["end"], "%Y-%m-%d %H:%M:%S.%f%z")
        assert beginning == previous_end
        assert ending - beginning < timedelta(days=50)
        assert payload["instProfileIds"] == [11]
        previous_end = ending
    assert previous_end == end


@pytest.mark.asyncio
async def test_range_uses_booked_interval_and_exclusive_end(client):
    start = datetime.fromisoformat("2026-11-02T09:20:00+01:00")
    end = start + timedelta(minutes=20)
    assert await client.get_meeting_bookings(11, start, end) == []
    assert len(await client.get_meeting_bookings(11, start, end + timedelta(minutes=1))) == 1
    assert (
        await client.get_meeting_bookings(11, end + timedelta(minutes=20), end + timedelta(hours=1))
        == []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"status": {"code": 403}, "data": []},
        {"data": []},
        {"status": {"code": 0}, "data": None},
    ],
)
async def test_invalid_or_rejected_response_raises(client, body):
    client._request_with_version_retry.return_value = HttpResponse(status_code=200, data=body)
    with pytest.raises(HttpRequestError):
        await client.get_meeting_bookings(
            11, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)
        )


@pytest.mark.asyncio
async def test_later_chunk_failure_never_returns_partial_results(client, row):
    client._request_with_version_retry.side_effect = [
        HttpResponse(status_code=200, data={"status": {"code": 0}, "data": [row]}),
        HttpResponse(status_code=200, data={"status": {"code": 403}, "data": []}),
    ]
    with pytest.raises(HttpRequestError):
        await client.get_meeting_bookings(
            11, datetime(2026, 10, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end",
    [
        (datetime(2026, 1, 1), datetime(2026, 2, 1)),
        (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
        (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
    ],
)
async def test_invalid_bounds_make_no_requests(client, start, end):
    with pytest.raises(ValueError):
        await client.get_meeting_bookings(11, start, end)
    client._request_with_version_retry.assert_not_awaited()


_WEEK = (
    datetime.fromisoformat("2026-11-02T00:00:00+01:00"),
    datetime.fromisoformat("2026-11-09T00:00:00+01:00"),
)


def _slots(calendar):
    return [(e.id, e.event_type, e.start_datetime.isoformat()) for e in calendar]


@pytest.mark.asyncio
async def test_by_child_shows_each_childs_booked_slot(client):
    """The shared meeting row becomes each child's own appointment."""
    calendars = await client.get_calendar_events_by_child([11, 12, 13], *_WEEK)

    assert {child: _slots(events) for child, events in calendars.items()} == {
        11: [(42, "school_home_meeting", "2026-11-02T09:40:00+01:00")],
        12: [(42, "school_home_meeting", "2026-11-02T09:00:00+01:00")],
        13: [],
    }
    assert calendars[11][0].belongs_to_profiles == [11]
    assert calendars[11][0].location == "Room A"


@pytest.mark.asyncio
async def test_by_child_keeps_an_unbooked_meeting_as_the_calendar_shows_it(client, row):
    row["timeSlot"]["timeSlots"][0]["answers"] = [
        {"concerningProfileId": 11, "selectedTimeSlotIndex": 1}
    ]

    calendars = await client.get_calendar_events_by_child([11, 12], *_WEEK)

    assert _slots(calendars[11]) == [(42, "school_home_meeting", "2026-11-02T09:40:00+01:00")]
    # Child 12 has not booked yet, so the whole booking period stays.
    assert _slots(calendars[12]) == [(42, "school_home_meeting", "2026-11-02T09:00:00+01:00")]
    assert calendars[12][0].end_datetime.isoformat() == "2026-11-09T12:00:00+01:00"


def test_replace_booked_meetings_leaves_other_events_with_the_same_id(row):
    booking = meeting_bookings([row], 11)[0]
    lesson = CalendarEvent(
        id=booking.meeting_id,
        title="Math",
        start_datetime=booking.start_datetime,
        end_datetime=booking.end_datetime,
        teacher_name=None,
        has_substitute=False,
        substitute_name=None,
        location=None,
        belongs_to=11,
        event_type="lesson",
    )

    assert replace_booked_meetings([lesson], [booking]) == [
        lesson,
        booking.as_calendar_event(),
    ]


@pytest.fixture
def cli_client(monkeypatch, row):
    fake = MagicMock()
    fake.get_profile = AsyncMock(
        return_value=Profile(
            profile_id=1,
            display_name="Parent",
            children=[
                Child(
                    id=11,
                    profile_id=21,
                    name="Barn Et",
                    institution_name="School",
                    profile_picture="",
                ),
                Child(
                    id=12,
                    profile_id=22,
                    name="Barn To",
                    institution_name="School",
                    profile_picture="",
                ),
            ],
        )
    )
    fake.get_meeting_bookings = AsyncMock(
        side_effect=lambda child, start, end: meeting_bookings([row], child)
    )
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("aula.cli._get_client", AsyncMock(return_value=fake))
    return fake


@pytest.mark.parametrize("output", ["text", "json"])
def test_cli_selected_child_and_output(cli_client, output):
    result = CliRunner().invoke(
        meetings,
        ["--child-id", "11", "--start-date", "2026-11-01", "--end-date", "2026-12-01"],
        obj={"OUTPUT_FORMAT": output},
    )
    assert result.exit_code == 0, result.output
    assert cli_client.get_meeting_bookings.await_args.args[0] == 11
    if output == "json":
        data = json.loads(result.output)
        assert data[0]["child_name"] == "Barn Et"
        assert data[0]["start_datetime"] == "2026-11-02T09:40:00+01:00"
    else:
        assert "Barn Et: Reading discussion" in result.output
        assert "09:40" in result.output
        assert "Room A" in result.output


def test_cli_defaults_to_all_children_and_100_days(cli_client):
    result = CliRunner().invoke(meetings, obj={"OUTPUT_FORMAT": "json"})
    assert result.exit_code == 0, result.output
    assert [c.args[0] for c in cli_client.get_meeting_bookings.await_args_list] == [11, 12]
    _, start, end = cli_client.get_meeting_bookings.await_args.args
    assert end - start == timedelta(days=100)


def test_cli_unknown_child_fails(cli_client):
    result = CliRunner().invoke(meetings, ["--child-id", "999"], obj={})
    assert result.exit_code != 0
    cli_client.get_meeting_bookings.assert_not_awaited()


def test_cli_failure_exits_nonzero_without_partial_json(cli_client):
    cli_client.get_meeting_bookings.side_effect = [[], HttpRequestError("Rejected", 403)]
    result = CliRunner().invoke(meetings, obj={"OUTPUT_FORMAT": "json"})
    assert result.exit_code != 0
    assert "fetching booked meetings" in result.output


@pytest.mark.parametrize("output", ["text", "json"])
def test_cli_empty_bookings(cli_client, output):
    cli_client.get_meeting_bookings.side_effect = None
    cli_client.get_meeting_bookings.return_value = []
    result = CliRunner().invoke(meetings, obj={"OUTPUT_FORMAT": output})
    assert result.exit_code == 0, result.output
    if output == "json":
        assert json.loads(result.output) == []
    else:
        assert "No booked meetings" in result.output


def test_cli_reversed_dates_fail_before_requests(cli_client):
    result = CliRunner().invoke(
        meetings, ["--start-date", "2026-12-01", "--end-date", "2026-11-01"], obj={}
    )
    assert result.exit_code != 0
    cli_client.get_meeting_bookings.assert_not_awaited()
