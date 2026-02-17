from dataclasses import dataclass, field

from .base import AulaDataClass


@dataclass
class Institution(AulaDataClass):
    institution_code: str
    institution_name: str
    _raw: dict | None = field(default=None, repr=False)
