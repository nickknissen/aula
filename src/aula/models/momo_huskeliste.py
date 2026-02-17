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
