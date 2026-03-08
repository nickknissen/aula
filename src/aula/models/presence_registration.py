import logging
from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass
from .presence import PresenceState

_LOGGER = logging.getLogger(__name__)


@dataclass
class PresenceRegistration(AulaDataClass):
    """A presence registration record for a child on a given date."""

    id: int | None = None
    institution_profile_id: int | None = None
    status: PresenceState | None = None
    date: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceRegistration":
        status_value = data.get("status")
        presence_status = None
        if status_value is not None:
            try:
                presence_status = PresenceState(status_value)
            except ValueError:
                _LOGGER.warning("Unknown presence status value: %s", status_value)

        return cls(
            _raw=data,
            id=data.get("id"),
            institution_profile_id=data.get("institutionProfileId"),
            status=presence_status,
            date=data.get("date"),
            entry_time=data.get("entryTime"),
            exit_time=data.get("exitTime"),
            check_in_time=data.get("checkInTime"),
            check_out_time=data.get("checkOutTime"),
        )


@dataclass
class PresenceRegistrationDetail(AulaDataClass):
    """Detailed presence registration info for a single record."""

    id: int | None = None
    child_name: str | None = None
    institution_profile_id: int | None = None
    status: PresenceState | None = None
    date: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    exit_with: str | None = None
    comment: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceRegistrationDetail":
        status_value = data.get("status")
        presence_status = None
        if status_value is not None:
            try:
                presence_status = PresenceState(status_value)
            except ValueError:
                _LOGGER.warning("Unknown presence status value: %s", status_value)

        return cls(
            _raw=data,
            id=data.get("id"),
            child_name=data.get("childName"),
            institution_profile_id=data.get("institutionProfileId"),
            status=presence_status,
            date=data.get("date"),
            entry_time=data.get("entryTime"),
            exit_time=data.get("exitTime"),
            check_in_time=data.get("checkInTime"),
            check_out_time=data.get("checkOutTime"),
            exit_with=data.get("exitWith"),
            comment=data.get("comment"),
        )


@dataclass
class ChildPresenceState(AulaDataClass):
    """Current presence state for a child."""

    institution_profile_id: int | None = None
    name: str | None = None
    status: PresenceState | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChildPresenceState":
        # The API uses "state" (not "status") at the top level
        status_value = data.get("state", data.get("status"))
        presence_status = None
        if status_value is not None:
            try:
                presence_status = PresenceState(status_value)
            except ValueError:
                _LOGGER.warning("Unknown presence status value: %s", status_value)

        # Profile ID and name are nested inside uniStudent
        uni_student = data.get("uniStudent", {}) or {}
        institution_profile_id = uni_student.get("id") or data.get("institutionProfileId")
        name = uni_student.get("name")

        return cls(
            _raw=data,
            institution_profile_id=institution_profile_id,
            name=name,
            status=presence_status,
        )


@dataclass
class PresenceConfiguration(AulaDataClass):
    """Presence configuration for a child (pickup rules, etc.)."""

    child_id: int | None = None
    institution_code: str | None = None
    institution_name: str | None = None
    pickup: bool | None = None
    go_home_with: bool | None = None
    self_decider: bool | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceConfiguration":
        # Real API nests config under "presenceConfiguration"
        config = data.get("presenceConfiguration", {}) or {}
        institution = config.get("institution", {}) or {}

        return cls(
            _raw=data,
            child_id=data.get("uniStudentId") or data.get("childId"),
            institution_code=institution.get("institutionCode"),
            institution_name=institution.get("name"),
            pickup=config.get("pickup"),
            go_home_with=config.get("goHomeWith"),
            self_decider=config.get("selfDecider"),
        )


@dataclass
class PresenceActivity(AulaDataClass):
    """A single activity within a day of the week overview."""

    title: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceActivity":
        return cls(
            _raw=data,
            title=data.get("title"),
            start_time=data.get("startTime"),
            end_time=data.get("endTime"),
        )


@dataclass
class PresenceDay(AulaDataClass):
    """A single day in the week overview."""

    date: str | None = None
    activities: list[PresenceActivity] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceDay":
        return cls(
            _raw=data,
            date=data.get("date"),
            activities=[PresenceActivity.from_dict(a) for a in data.get("activities", []) if a],
        )


@dataclass
class PresenceWeekOverview(AulaDataClass):
    """Week overview of presence activities."""

    days: list[PresenceDay] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceWeekOverview":
        return cls(
            _raw=data,
            days=[PresenceDay.from_dict(d) for d in data.get("days", []) if d],
        )
