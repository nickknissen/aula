from dataclasses import dataclass, field

from .base import AulaDataClass


@dataclass
class ProfilePicture(AulaDataClass):
    url: str | None = None
    _raw: dict | None = field(default=None, repr=False)
