from dataclasses import dataclass, field

from .base import AulaDataClass


@dataclass
class Appointment(AulaDataClass):
    appointment_id: str
    title: str
    _raw: dict | None = field(default=None, repr=False)
