from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class PickupPerson(AulaDataClass):
    """A person who can pick up a child (family member or saved suggestion)."""

    name: str = ""
    relation: str | None = None
    institution_profile_id: int | None = None
    suggestion_id: int | None = None
    _raw: dict | None = field(default=None, repr=False)


@dataclass
class ChildPickupResponsibles(AulaDataClass):
    """Pickup responsibles for a single child."""

    uni_student_id: int = 0
    persons: list[PickupPerson] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChildPickupResponsibles":
        persons: list[PickupPerson] = []

        for rp in data.get("relatedPersons", []):
            persons.append(
                PickupPerson(
                    name=rp.get("name", ""),
                    relation=rp.get("relation"),
                    institution_profile_id=rp.get("institutionProfileId"),
                    _raw=rp,
                )
            )

        for ps in data.get("pickupSuggestions", []):
            persons.append(
                PickupPerson(
                    name=ps.get("pickUpName", ""),
                    suggestion_id=ps.get("id"),
                    _raw=ps,
                )
            )

        return cls(
            _raw=data,
            uni_student_id=data.get("uniStudentId", 0),
            persons=persons,
        )
