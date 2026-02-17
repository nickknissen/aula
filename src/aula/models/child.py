from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class Child(AulaDataClass):
    id: int
    profile_id: int
    name: str
    institution_name: str
    profile_picture: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Child":
        return cls(
            _raw=data,
            id=data["id"],
            profile_id=data["profileId"],
            name=data["name"],
            institution_name=data.get("institutionProfile", {}).get("institutionName", ""),
            profile_picture=data.get("profilePicture", {}).get("url", ""),
        )
