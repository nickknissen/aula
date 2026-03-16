from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class Group(AulaDataClass):
    id: int
    name: str
    group_type: str = ""
    institution_code: str = ""
    description: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Group":
        return cls(
            _raw=data,
            id=data["id"],
            name=data.get("name", ""),
            group_type=data.get("type", ""),
            institution_code=str(data.get("institutionCode", "")),
            description=data.get("description", ""),
        )


@dataclass
class GroupMember(AulaDataClass):
    institution_profile_id: int
    name: str
    portal_role: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroupMember":
        return cls(
            _raw=data,
            institution_profile_id=data["institutionProfileId"],
            name=data.get("name", ""),
            portal_role=data.get("portalRole", ""),
        )
