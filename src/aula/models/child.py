from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class Child(AulaDataClass):
    """A child in the user's profile.

    Note: This class has two different ID fields:
    - `id`: Institution profile ID (used for API calls like get_calendar_events, get_posts)
    - `profile_id`: User's profile ID (displayed to users as "Profile ID")

    Always use `id` when making API calls for this child.
    """

    id: int  # Institution profile ID - use this for API calls
    profile_id: int  # User profile ID - displayed to users
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
