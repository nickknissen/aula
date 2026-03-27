from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class ConsentResponse(AulaDataClass):
    id: int
    consent_id: int
    title: str = ""
    description: str = ""
    status: str = ""
    responded_at: str | None = None
    institution_code: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConsentResponse":
        return cls(
            _raw=data,
            id=data.get("id", 0),
            consent_id=data.get("consentId", 0),
            title=data.get("title", "") or data.get("consentTitle", ""),
            description=data.get("description", ""),
            status=data.get("status", "") or data.get("responseStatus", ""),
            responded_at=data.get("respondedAt") or data.get("responseDate"),
            institution_code=str(data.get("institutionCode", "")),
        )
