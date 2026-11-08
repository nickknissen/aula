from dataclasses import dataclass, field
from typing import Any

from ..utils.mapping import get_in
from .base import AulaDataClass


@dataclass
class Child(AulaDataClass):
    """A child in the user's profile.

    Note: This class has three different ID fields:
    - `id`: Institution profile ID (used for API calls like get_calendar_events, get_posts)
    - `profile_id`: User's profile ID (displayed to users as "Profile ID")
    - `user_id`: UniLogin

    Always use `id` when making Aula API calls for this child.
    """

    id: int  # Institution profile ID - use this for API calls
    profile_id: int  # User profile ID - displayed to users
    name: str
    institution_name: str
    profile_picture: str
    user_id: str | None = None
    institution_code: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Child:
        return cls(
            _raw=data,
            id=data["id"],
            profile_id=data["profileId"],
            name=data["name"],
            institution_name=get_in(data, "institutionProfile.institutionName", default=""),
            profile_picture=get_in(data, "profilePicture.url", default=""),
            user_id=_optional_str(data.get("userId")),
            institution_code=_optional_str(get_in(data, "institutionProfile.institutionCode")),
        )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
