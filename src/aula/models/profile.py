from dataclasses import dataclass, field

from .base import AulaDataClass
from .child import Child


@dataclass
class Profile(AulaDataClass):
    profile_id: int
    display_name: str
    children: list[Child] = field(default_factory=list)
    institution_profile_ids: list[int] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)
