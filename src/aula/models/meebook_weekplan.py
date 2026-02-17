from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class MeebookTask(AulaDataClass):
    id: int
    type: str
    title: str
    content: str
    pill: str
    link_text: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MeebookTask":
        return cls(
            _raw=data,
            id=data.get("id", 0),
            type=data.get("type", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            pill=data.get("pill", ""),
            link_text=data.get("link_text", ""),
        )


@dataclass
class MeebookDayPlan(AulaDataClass):
    date: str
    tasks: list[MeebookTask] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MeebookDayPlan":
        tasks = [MeebookTask.from_dict(t) for t in data.get("tasks", [])]
        return cls(
            _raw=data,
            date=data.get("date", ""),
            tasks=tasks,
        )


@dataclass
class MeebookStudentPlan(AulaDataClass):
    name: str
    unilogin: str
    week_plan: list[MeebookDayPlan] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MeebookStudentPlan":
        week_plan = [MeebookDayPlan.from_dict(d) for d in data.get("weekPlan", [])]
        return cls(
            _raw=data,
            name=data.get("name", ""),
            unilogin=data.get("unilogin", ""),
            week_plan=week_plan,
        )
