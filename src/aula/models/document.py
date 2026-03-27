from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class SecureDocument(AulaDataClass):
    id: int
    title: str = ""
    document_type: str = ""
    description: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    owner_name: str = ""
    institution_code: str = ""
    is_read: bool = False
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecureDocument":
        owner = data.get("owner") or {}
        owner_name = ""
        if isinstance(owner, dict):
            owner_name = owner.get("name", "") or owner.get("displayName", "")
        elif isinstance(owner, str):
            owner_name = owner

        return cls(
            _raw=data,
            id=data.get("id", 0),
            title=data.get("title", ""),
            document_type=data.get("type", "") or data.get("documentType", ""),
            description=data.get("description", ""),
            created_at=data.get("createdAt") or data.get("creationDate"),
            updated_at=data.get("updatedAt") or data.get("lastEditDate"),
            owner_name=owner_name,
            institution_code=str(data.get("institutionCode", "")),
            is_read=bool(data.get("isRead", False)),
        )
