from dataclasses import dataclass

from .base import AulaDataClass


@dataclass
class SfoWebStatus(AulaDataClass):
    """Current child status reported by IST SFOweb."""

    status: str | None
    time: str | None
    raw_text: str | None
