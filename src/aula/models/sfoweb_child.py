from dataclasses import dataclass

from .base import AulaDataClass


@dataclass
class SfoWebChild(AulaDataClass):
    """A child available in the authenticated SFOweb guardian session."""

    name: str
    child_id: str
    selector: str
