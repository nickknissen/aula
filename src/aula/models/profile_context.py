from dataclasses import dataclass, field

from .base import AulaDataClass


@dataclass
class ProfileContext(AulaDataClass):
    _raw: dict | None = field(default=None, repr=False)
