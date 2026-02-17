from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class ProfileReference(AulaDataClass):
    """Represents a reference to a profile in Aula."""

    id: int
    profile_id: int
    first_name: str
    last_name: str
    full_name: str
    short_name: str
    role: str
    institution_name: str
    profile_picture: dict | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProfileReference":
        return cls(
            id=data["id"],
            profile_id=data["profileId"],
            first_name=data.get("firstName", ""),
            last_name=data.get("lastName", ""),
            full_name=data.get("fullName", ""),
            short_name=data.get("shortName", ""),
            role=data.get("role", ""),
            institution_name=data.get("institution", {}).get("institutionName", ""),
            profile_picture=data.get("profilePicture"),
            _raw=data,
        )
