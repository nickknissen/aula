from dataclasses import dataclass, field
from typing import Any

from ..utils.mapping import get_in
from .base import AulaDataClass


@dataclass
class CommonFile(AulaDataClass):
    id: int
    title: str = ""
    created_at: str | None = None
    institution_code: str = ""
    institution_name: str = ""
    file_name: str = ""
    file_url: str = ""
    is_data_policy: bool = False
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommonFile:
        return cls(
            _raw=data,
            id=data["id"],
            title=data.get("title") or "",
            created_at=data.get("created"),
            institution_code=str(get_in(data, "institution.institutionCode", default="")),
            institution_name=get_in(data, "institution.name", default=""),
            file_name=get_in(data, "file.name", default="")
            or get_in(data, "file.file.name", default=""),
            file_url=get_in(data, "file.file.url", default=""),
            is_data_policy=bool(data.get("isDataPolicy", False)),
        )
