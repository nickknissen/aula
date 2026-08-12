from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class VacationRegistration(AulaDataClass):
    """A vacation registration the institution asks a guardian to answer.

    Aula returns these grouped by child from
    `presence.getVacationRegistrationsByChildren`. Each row is flattened here so
    the child it belongs to travels with the registration.
    """

    id: int
    child_id: int = 0
    child_name: str = ""
    title: str = ""
    start_date: str | None = None
    end_date: str | None = None
    response_id: int = 0
    response_deadline: str | None = None
    note_to_guardian: str = ""
    is_editable: bool = False
    is_missing_answer: bool = False
    is_presence_times_required: bool = False
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], child: dict[str, Any] | None = None
    ) -> VacationRegistration:
        child = child or {}
        return cls(
            _raw=data,
            id=data.get("vacationRegistrationId", 0),
            child_id=child.get("id", 0),
            child_name=child.get("name", ""),
            title=data.get("title", ""),
            start_date=data.get("startDate"),
            end_date=data.get("endDate"),
            response_id=data.get("responseId", 0),
            response_deadline=data.get("responseDeadline"),
            note_to_guardian=data.get("noteToGuardian", "") or "",
            is_editable=data.get("isEditable", False),
            is_missing_answer=data.get("isMissingAnswer", False),
            is_presence_times_required=data.get("isPresenceTimesRequired", False),
        )
