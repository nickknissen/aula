from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class Comment(AulaDataClass):
    id: int
    content_html: str
    creator_name: str
    creator_institution_profile_id: int | None = None
    created_at: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @property
    def content(self) -> str:
        from ..utils.html import html_to_plain

        return html_to_plain(self.content_html)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Comment":
        owner = data.get("owner", {}) or {}
        return cls(
            _raw=data,
            id=data["id"],
            content_html=data.get("text", ""),
            creator_name=owner.get("name", data.get("creatorName", "")),
            creator_institution_profile_id=data.get("creatorInstitutionProfileId")
            or owner.get("institutionProfileId"),
            created_at=data.get("createdAt", ""),
        )
