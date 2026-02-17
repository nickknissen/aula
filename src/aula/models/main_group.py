from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class MainGroup(AulaDataClass):
    id: int | None = None
    name: str | None = None
    short_name: str | None = None
    institution_code: str | None = None
    institution_name: str | None = None
    uni_group_type: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MainGroup":
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            short_name=data.get("shortName"),
            institution_code=data.get("institutionCode"),
            institution_name=data.get("institutionName"),
            uni_group_type=data.get("uniGroupType"),
        )
