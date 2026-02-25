from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass
from .profile_picture import ProfilePicture


@dataclass
class InstitutionProfile(AulaDataClass):
    """An institution profile (child's profile at a school/institution).

    Note: This class has two different ID fields:
    - `id`: Institution profile ID (matches Child.id, used for API calls)
    - `profile_id`: User's profile ID (matches Child.profile_id)

    When mapping children to institution profiles, always match on the `id` field.
    """

    profile_id: int | None = None  # User profile ID
    id: int | None = None  # Institution profile ID - use for matching with Child.id
    institution_code: str | None = None
    institution_name: str | None = None
    role: str | None = None
    name: str | None = None
    profile_picture: ProfilePicture | None = None
    short_name: str | None = None
    institution_role: str | None = None
    metadata: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstitutionProfile":
        pic_data = data.get("profilePicture", {})
        return cls(
            profile_id=data.get("profileId"),
            id=data.get("id"),
            institution_code=data.get("institutionCode"),
            institution_name=data.get("institutionName"),
            role=data.get("role"),
            name=data.get("name"),
            profile_picture=ProfilePicture(url=pic_data.get("url")) if pic_data else None,
            short_name=data.get("shortName"),
            institution_role=data.get("institutionRole"),
            metadata=data.get("metadata"),
        )
