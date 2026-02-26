"""Tests for widget token and provider endpoints."""

from unittest.mock import AsyncMock, Mock, call

import pytest

from aula.api_client import AulaApiClient
from aula.const import (
    CICERO_API,
    EASYIQ_API,
    MEEBOOK_API,
    MIN_UDDANNELSE_API,
    SYSTEMATIC_API,
    WIDGET_HUSKELISTEN,
    WIDGET_MIN_UDDANNELSE,
)


class TestWidgetsClient:
    @pytest.fixture
    def client(self):
        return AulaApiClient(http_client=AsyncMock(), access_token="token")

    @pytest.mark.asyncio
    async def test_get_bearer_token_calls_raise_for_status_before_json(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-123"})
        client._request_with_version_retry = AsyncMock(return_value=token_response)

        token = await client.widgets._get_bearer_token("0030")

        assert token == "Bearer token-123"
        client._request_with_version_retry.assert_awaited_once_with(
            "get", f"{client.api_url}?method=aulaToken.getAulaToken&widgetId=0030"
        )
        assert token_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_mu_tasks_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-123"})

        tasks_response = Mock()
        tasks_response.raise_for_status = Mock()
        tasks_response.json = Mock(
            return_value={
                "opgaver": [
                    {
                        "id": "task-1",
                        "title": "Task 1",
                    }
                ]
            }
        )

        client._request_with_version_retry = AsyncMock(side_effect=[token_response, tasks_response])

        tasks = await client.widgets.get_mu_tasks(
            widget_id=WIDGET_MIN_UDDANNELSE,
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert [task.id for task in tasks] == ["task-1"]
        assert client._request_with_version_retry.await_count == 2

        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{MIN_UDDANNELSE_API}/opgaveliste")
        assert calls[1].kwargs["params"] == {
            "placement": "narrow",
            "sessionUUID": "session-1",
            "userProfile": "guardian",
            "currentWeekNumber": "2026-W09",
            "isMobileApp": "false",
            "childFilter[]": ["child-1"],
            "institutionFilter[]": ["inst-1"],
        }
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-123",
            "Accept": "application/json",
        }
        assert tasks_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_ugeplan_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-abc"})

        ugeplan_response = Mock()
        ugeplan_response.raise_for_status = Mock()
        ugeplan_response.json = Mock(
            return_value={"personer": [{"id": 1, "navn": "Student", "uniLogin": "student1"}]}
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, ugeplan_response]
        )

        persons = await client.widgets.get_ugeplan(
            widget_id=WIDGET_MIN_UDDANNELSE,
            child_filter=["child-1", "child-2"],
            institution_filter=["inst-1", "inst-2"],
            week="2026-W09",
            session_uuid="session-1",
        )

        assert [person.id for person in persons] == [1]
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{MIN_UDDANNELSE_API}/ugebrev")
        assert calls[1].kwargs["params"] == {
            "assuranceLevel": "3",
            "childFilter": "child-1,child-2",
            "currentWeekNumber": "2026-W09",
            "institutionFilter": "inst-1,inst-2",
            "isMobileApp": "false",
            "placement": "narrow",
            "sessionUUID": "session-1",
            "userProfile": "guardian",
        }
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-abc",
            "Accept": "application/json",
        }
        assert ugeplan_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_easyiq_weekplan_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-easy"})

        easyiq_response = Mock()
        easyiq_response.raise_for_status = Mock()
        easyiq_response.json = Mock(
            return_value={
                "data": {
                    "appointments": [
                        {
                            "appointmentId": "apt-1",
                            "title": "Math",
                            "start": "2026-02-24 08:00",
                            "end": "2026-02-24 09:00",
                            "description": "<p>Algebra</p>",
                            "itemType": 9,
                        }
                    ]
                }
            }
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, easyiq_response]
        )

        appointments = await client.widgets.get_easyiq_weekplan(
            week="2026-W09",
            session_uuid="session-1",
            institution_filter=["inst-1", "inst-2"],
            child_id="child-1",
        )

        assert [appointment.appointment_id for appointment in appointments] == ["apt-1"]
        assert appointments[0].start == "2026-02-24 08:00"
        assert appointments[0].end == "2026-02-24 09:00"
        assert appointments[0].description == "<p>Algebra</p>"
        assert appointments[0].item_type == 9
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("post", f"{EASYIQ_API}/weekplaninfo")
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-easy",
            "x-aula-institutionfilter": "inst-1,inst-2",
        }
        assert calls[1].kwargs["json"] == {
            "sessionId": "session-1",
            "currentWeekNr": "2026-W09",
            "userProfile": "guardian",
            "institutionFilter": ["inst-1", "inst-2"],
            "childFilter": ["child-1"],
        }
        assert easyiq_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_easyiq_homework_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-easy-hw"})

        homework_response = Mock()
        homework_response.raise_for_status = Mock()
        homework_response.json = Mock(
            return_value={
                "data": {
                    "homework": [
                        {
                            "id": "hw-1",
                            "title": "Read chapter 5",
                            "description": "<p>Pages 40-55</p>",
                            "dueDate": "2026-02-28",
                            "subject": "Danish",
                            "isCompleted": False,
                        }
                    ]
                }
            }
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, homework_response]
        )

        homework = await client.widgets.get_easyiq_homework(
            week="2026-W09",
            session_uuid="session-1",
            institution_filter=["inst-1", "inst-2"],
            child_id="child-1",
        )

        assert len(homework) == 1
        assert homework[0].id == "hw-1"
        assert homework[0].title == "Read chapter 5"
        assert homework[0].description == "<p>Pages 40-55</p>"
        assert homework[0].due_date == "2026-02-28"
        assert homework[0].subject == "Danish"
        assert homework[0].is_completed is False

        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("post", f"{EASYIQ_API}/homeworkinfo")
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-easy-hw",
            "x-aula-institutionfilter": "inst-1,inst-2",
        }
        assert calls[1].kwargs["json"] == {
            "sessionId": "session-1",
            "currentWeekNr": "2026-W09",
            "userProfile": "guardian",
            "institutionFilter": ["inst-1", "inst-2"],
            "childFilter": ["child-1"],
        }
        assert homework_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_meebook_weekplan_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-meebook"})

        meebook_response = Mock()
        meebook_response.raise_for_status = Mock()
        meebook_response.json = Mock(
            return_value=[
                {
                    "name": "Student",
                    "unilogin": "student1",
                    "weekPlan": [
                        {
                            "date": "2026-02-24",
                            "tasks": [
                                {
                                    "id": 1,
                                    "type": "task",
                                    "title": "Read",
                                    "content": "Chapter 1",
                                    "pill": "Homework",
                                    "link_text": "Open",
                                }
                            ],
                        }
                    ],
                }
            ]
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, meebook_response]
        )

        plans = await client.widgets.get_meebook_weekplan(
            child_filter=["child-1"],
            institution_filter=["inst-1"],
            week="2026-W9",
            session_uuid="session-1",
        )

        assert [plan.unilogin for plan in plans] == ["student1"]
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{MEEBOOK_API}/relatedweekplan/all")
        assert calls[1].kwargs["params"] == {
            "currentWeekNumber": "2026-W09",
            "userProfile": "guardian",
            "childFilter[]": ["child-1"],
            "institutionFilter[]": ["inst-1"],
        }
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-meebook",
            "Accept": "application/json",
            "sessionUUID": "session-1",
            "X-Version": "1.0",
        }
        assert meebook_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_momo_courses_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-momo"})

        momo_response = Mock()
        momo_response.raise_for_status = Mock()
        momo_response.json = Mock(
            return_value=[
                {
                    "userId": "child-1",
                    "name": "Student",
                    "courses": [
                        {
                            "id": "course-1",
                            "title": "Danish",
                            "institutionId": "inst-1",
                            "image": None,
                        }
                    ],
                }
            ]
        )

        client._request_with_version_retry = AsyncMock(side_effect=[token_response, momo_response])

        courses = await client.widgets.get_momo_courses(
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
        )

        assert [course.user_id for course in courses] == ["child-1"]
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{SYSTEMATIC_API}/courses/v1")
        assert calls[1].kwargs["params"] == {
            "widgetVersion": "1.3",
            "userProfile": "guardian",
            "sessionId": "session-1",
            "children": ["child-1"],
            "institutions": ["inst-1"],
        }
        assert calls[1].kwargs["headers"] == {
            "Aula-Authorization": "Bearer token-momo",
        }
        assert momo_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_momo_reminders_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-momo"})

        reminders_response = Mock()
        reminders_response.raise_for_status = Mock()
        reminders_response.json = Mock(
            return_value=[
                {
                    "userId": 164625,
                    "userName": "Emilie Efternavn",
                    "courseReminders": [],
                    "assignmentReminders": [
                        {
                            "id": 1,
                            "institutionName": "Holme Skole",
                            "institutionId": 183,
                            "dueDate": "2026-03-01T11:00:00Z",
                            "courseId": 297469,
                            "teamNames": ["5A"],
                            "teamIds": [65271],
                            "courseSubjects": [],
                            "assignmentId": 5027904,
                            "assignmentText": "Skriv en novelle",
                        }
                    ],
                    "teamReminders": [
                        {
                            "id": 76169,
                            "institutionName": "Holme Skole",
                            "institutionId": 183,
                            "dueDate": "2026-02-28T23:00:00Z",
                            "teamId": 65240,
                            "teamName": "2A",
                            "reminderText": "Lektie: Matematikfessor",
                            "createdBy": "Peter",
                            "lastEditBy": "Peter",
                            "subjectName": "Matematik",
                        }
                    ],
                }
            ]
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, reminders_response]
        )

        users = await client.widgets.get_momo_reminders(
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
            from_date="2026-02-26",
            due_no_later_than="2026-03-05",
        )

        assert len(users) == 1
        assert users[0].user_name == "Emilie Efternavn"
        assert len(users[0].team_reminders) == 1
        assert users[0].team_reminders[0].subject_name == "Matematik"
        assert len(users[0].assignment_reminders) == 1
        assert users[0].assignment_reminders[0].assignment_text == "Skriv en novelle"

        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{SYSTEMATIC_API}/reminders/v1")
        assert calls[1].kwargs["params"] == {
            "widgetVersion": "1.10",
            "userProfile": "guardian",
            "sessionId": "session-1",
            "children": ["child-1"],
            "institutions": ["inst-1"],
            "from": "2026-02-26",
            "dueNoLaterThan": "2026-03-05",
        }
        assert calls[1].kwargs["headers"] == {
            "Aula-Authorization": "Bearer token-momo",
        }
        assert reminders_response.method_calls == [call.raise_for_status(), call.json()]

    @pytest.mark.asyncio
    async def test_get_library_status_uses_token_and_expected_request_shape(self, client):
        token_response = Mock()
        token_response.raise_for_status = Mock()
        token_response.json = Mock(return_value={"data": "token-library"})

        library_response = Mock()
        library_response.raise_for_status = Mock()
        library_response.json = Mock(
            return_value={
                "loans": [
                    {
                        "id": 1,
                        "title": "Book",
                        "author": "Author",
                        "patronDisplayName": "Student",
                        "dueDate": "2026-03-01",
                        "numberOfLoans": 1,
                    }
                ],
                "longtermLoans": [],
                "reservations": [],
                "branchIds": ["branch-1"],
            }
        )

        client._request_with_version_retry = AsyncMock(
            side_effect=[token_response, library_response]
        )

        status = await client.widgets.get_library_status(
            widget_id=WIDGET_HUSKELISTEN,
            children=["child-1"],
            institutions=["inst-1"],
            session_uuid="session-1",
        )

        assert [loan.id for loan in status.loans] == [1]
        calls = client._request_with_version_retry.await_args_list
        assert calls[1].args == ("get", f"{CICERO_API}/library/status/v3")
        assert calls[1].kwargs["params"] == {
            "coverImageHeight": "160",
            "widgetVersion": "1.6",
            "userProfile": "guardian",
            "sessionUUID": "session-1",
            "institutions": ["inst-1"],
            "children": ["child-1"],
        }
        assert calls[1].kwargs["headers"] == {
            "Authorization": "Bearer token-library",
            "Accept": "application/json",
        }
        assert library_response.method_calls == [call.raise_for_status(), call.json()]
