from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class MUWeeklyLetter(AulaDataClass):
    group_id: int
    group_name: str
    content_html: str
    week_number: int
    sort_order: int
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MUWeeklyLetter":
        return cls(
            _raw=data,
            group_id=data.get("tilknytningId", 0),
            group_name=data.get("tilknytningNavn", ""),
            content_html=data.get("indhold", ""),
            week_number=data.get("uge", 0),
            sort_order=data.get("sortOrder", 0),
        )


@dataclass
class MUWeeklyInstitution(AulaDataClass):
    name: str
    code: int
    letters: list[MUWeeklyLetter] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MUWeeklyInstitution":
        return cls(
            _raw=data,
            name=data.get("navn", ""),
            code=data.get("kode", 0),
            letters=[MUWeeklyLetter.from_dict(u) for u in data.get("ugebreve", [])],
        )


@dataclass
class MUWeeklyPerson(AulaDataClass):
    name: str
    id: int
    unilogin: str
    institutions: list[MUWeeklyInstitution] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MUWeeklyPerson":
        return cls(
            _raw=data,
            name=data.get("navn", ""),
            id=data.get("id", 0),
            unilogin=data.get("uniLogin", ""),
            institutions=[MUWeeklyInstitution.from_dict(i) for i in data.get("institutioner", [])],
        )
