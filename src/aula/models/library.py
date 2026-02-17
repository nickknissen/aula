from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class LibraryLoan(AulaDataClass):
    id: int
    title: str
    author: str
    patron_display_name: str
    due_date: str
    number_of_loans: int
    cover_image_url: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LibraryLoan":
        return cls(
            _raw=data,
            id=data.get("id", 0),
            title=data.get("title", ""),
            author=data.get("author", ""),
            patron_display_name=data.get("patronDisplayName", ""),
            due_date=data.get("dueDate", ""),
            number_of_loans=data.get("numberOfLoans", 0),
            cover_image_url=data.get("coverImageUrl", ""),
        )


@dataclass
class LibraryStatus(AulaDataClass):
    loans: list[LibraryLoan] = field(default_factory=list)
    longterm_loans: list[LibraryLoan] = field(default_factory=list)
    reservations: list[dict] = field(default_factory=list)
    branch_ids: list[str] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LibraryStatus":
        return cls(
            _raw=data,
            loans=[LibraryLoan.from_dict(item) for item in data.get("loans", [])],
            longterm_loans=[LibraryLoan.from_dict(item) for item in data.get("longtermLoans", [])],
            reservations=data.get("reservations", []),
            branch_ids=data.get("branchIds", []),
        )
