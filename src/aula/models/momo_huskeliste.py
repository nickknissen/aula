from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class MomoCourse(AulaDataClass):
    id: str
    title: str
    institution_id: str
    image: str | None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MomoCourse":
        return cls(
            _raw=data,
            id=str(data.get("id", "")),
            title=data.get("title", data.get("name", "")),
            institution_id=str(data.get("institutionId", "")),
            image=data.get("image"),
        )


@dataclass
class MomoUserCourses(AulaDataClass):
    user_id: str
    name: str
    courses: list[MomoCourse] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MomoUserCourses":
        courses = [MomoCourse.from_dict(c) for c in data.get("courses", [])]
        return cls(
            _raw=data,
            user_id=str(data.get("userId", "")),
            name=data.get("name", ""),
            courses=courses,
        )


@dataclass
class TeamReminder(AulaDataClass):
    id: int
    institution_name: str
    institution_id: int
    due_date: str
    team_id: int
    team_name: str
    reminder_text: str
    created_by: str
    last_edit_by: str
    subject_name: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TeamReminder":
        return cls(
            _raw=data,
            id=data.get("id", 0),
            institution_name=data.get("institutionName", ""),
            institution_id=data.get("institutionId", 0),
            due_date=data.get("dueDate", ""),
            team_id=data.get("teamId", 0),
            team_name=data.get("teamName", ""),
            reminder_text=data.get("reminderText", ""),
            created_by=data.get("createdBy", ""),
            last_edit_by=data.get("lastEditBy", ""),
            subject_name=data.get("subjectName", ""),
        )


@dataclass
class AssignmentReminder(AulaDataClass):
    id: int
    institution_name: str
    institution_id: int
    due_date: str
    course_id: int
    team_names: list[str]
    team_ids: list[int]
    assignment_id: int
    assignment_text: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssignmentReminder":
        return cls(
            _raw=data,
            id=data.get("id", 0),
            institution_name=data.get("institutionName", ""),
            institution_id=data.get("institutionId", 0),
            due_date=data.get("dueDate", ""),
            course_id=data.get("courseId", 0),
            team_names=data.get("teamNames", []),
            team_ids=data.get("teamIds", []),
            assignment_id=data.get("assignmentId", 0),
            assignment_text=data.get("assignmentText", ""),
        )


@dataclass
class UserReminders(AulaDataClass):
    user_id: int
    user_name: str
    team_reminders: list[TeamReminder] = field(default_factory=list)
    assignment_reminders: list[AssignmentReminder] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserReminders":
        team = [TeamReminder.from_dict(r) for r in data.get("teamReminders", [])]
        assignment = [AssignmentReminder.from_dict(r) for r in data.get("assignmentReminders", [])]
        return cls(
            _raw=data,
            user_id=data.get("userId", 0),
            user_name=data.get("userName", ""),
            team_reminders=team,
            assignment_reminders=assignment,
        )
