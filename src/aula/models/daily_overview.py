import dataclasses
from dataclasses import dataclass, field
from typing import Any

from ..utils.diagnostics import credential_logger
from .base import AulaDataClass
from .institution_profile import InstitutionProfile
from .main_group import MainGroup
from .presence import PresenceState
from .presence_location import PresenceLocation

_LOGGER = credential_logger(__name__)

# Sleep intervals from the API are dicts with string keys (e.g. start/end times).
# The exact shape is undocumented, so we use dict[str, str] as the best known type.
SleepInterval = dict[str, str]


@dataclass
class DailyOverview(AulaDataClass):
    id: int | None = None
    institution_profile: InstitutionProfile | None = None
    main_group: MainGroup | None = None
    status: PresenceState | None = None
    location: PresenceLocation | None = None
    sleep_intervals: list[SleepInterval] = dataclasses.field(default_factory=list)
    check_in_time: str | None = None
    check_out_time: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    exit_with: str | None = None
    comment: str | None = None
    is_default_entry_time: bool = False
    is_default_exit_time: bool = False
    self_decider_start_time: str | None = None
    self_decider_end_time: str | None = None
    _raw: dict[str, Any] | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, raw_data: dict[str, Any]) -> DailyOverview:
        status_value = raw_data.get("status")
        presence_status = None
        if status_value is not None:
            try:
                presence_status = PresenceState(status_value)
            except ValueError:
                _LOGGER.warning("Unknown presence status value received: %s", status_value)

        inst_data = raw_data.get("institutionProfile")
        mg_data = raw_data.get("mainGroup")

        return cls(
            _raw=raw_data,
            id=raw_data.get("id"),
            status=presence_status,
            location=PresenceLocation.parse(raw_data.get("location")),
            sleep_intervals=raw_data.get("sleepIntervals", []),
            check_in_time=raw_data.get("checkInTime"),
            check_out_time=raw_data.get("checkOutTime"),
            entry_time=raw_data.get("entryTime"),
            exit_time=raw_data.get("exitTime"),
            exit_with=raw_data.get("exitWith"),
            comment=raw_data.get("comment"),
            is_default_entry_time=bool(raw_data.get("isDefaultEntryTime")),
            is_default_exit_time=bool(raw_data.get("isDefaultExitTime")),
            self_decider_start_time=raw_data.get("selfDeciderStartTime"),
            self_decider_end_time=raw_data.get("selfDeciderEndTime"),
            institution_profile=(
                InstitutionProfile.from_dict(inst_data) if isinstance(inst_data, dict) else None
            ),
            main_group=MainGroup.from_dict(mg_data) if isinstance(mg_data, dict) else None,
        )
