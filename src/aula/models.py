import dataclasses
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Any

# Logger
_LOGGER = logging.getLogger(__name__)

# Base Data model
@dataclass
class AulaDataClass:
    def __iter__(self):
        for f in dataclasses.fields(self):
            # Skip raw field and internal list fields
            if f.name == "_raw" or isinstance(getattr(self, f.name, None), list):
                continue
            # Also skip fields that are instances of other AulaDataClass unless explicitly handled
            # This basic iterator might need refinement for nested objects
            if isinstance(getattr(self, f.name, None), AulaDataClass):
                continue
            yield f.name, getattr(self, f.name)


# Data models
@dataclass
class Child(AulaDataClass):
    id: int
    profile_id: int
    name: str
    institution_code: str
    profile_picture: str
    _raw: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Child":
        """Parses the raw dictionary data into a Child object."""
        # Basic parsing, assumes 'data' is the child dictionary
        try:
            return cls(
                _raw=data,
                id=int(data.get("id")),
                profile_id=int(data.get("profileId")),
                name=str(data.get("name", "N/A")),
                institution_code=str(data.get("institutionCode", None)),
                profile_picture=str(data.get("profilePicture", {}).get("url", None)),
            )
        except (TypeError, ValueError) as e:
            _LOGGER.warning(f"Error parsing Child data: {e} - Data: {data}")
            # Decide on error handling: raise, return None, or return partial object
            # Returning a partially filled object or raising might be options
            # For now, re-raising to signal failure clearly
            raise ValueError(f"Could not parse Child from data: {data}") from e


@dataclass
class Profile(AulaDataClass):
    profile_id: int
    display_name: str
    children: List[Child] = field(default_factory=list)
    _raw: Optional[dict] = field(default=None, repr=False)


@dataclass
class ProfileContext(AulaDataClass):
    _raw: Optional[dict] = field(default=None, repr=False)


@dataclass
class ProfilePicture(AulaDataClass):
    url: Optional[str] = None
    _raw: Optional[dict] = field(default=None, repr=False)


@dataclass
class InstitutionProfile(AulaDataClass):
    profile_id: Optional[int] = None
    id: Optional[int] = None
    institution_code: Optional[str] = None
    institution_name: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    profile_picture: Optional[ProfilePicture] = None
    short_name: Optional[str] = None
    institution_role: Optional[str] = None
    metadata: Optional[str] = None
    _raw: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "InstitutionProfile":
        pic_data = data.get("profilePicture", {})
        return cls(
            profile_id=data.get("profileId"),
            id=data.get("id"),
            institution_code=data.get("institutionCode"),
            institution_name=data.get("institutionName"),
            role=data.get("role"),
            name=data.get("name"),
            profile_picture=ProfilePicture(url=pic_data.get("url"))
            if pic_data
            else None,
            short_name=data.get("shortName"),
            institution_role=data.get("institutionRole"),
            metadata=data.get("metadata"),
        )


@dataclass
class MainGroup(AulaDataClass):
    id: Optional[int] = None
    name: Optional[str] = None
    short_name: Optional[str] = None
    institution_code: Optional[str] = None
    institution_name: Optional[str] = None
    uni_group_type: Optional[str] = None
    _raw: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "MainGroup":
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            short_name=data.get("shortName"),
            institution_code=data.get("institutionCode"),
            institution_name=data.get("institutionName"),
            uni_group_type=data.get("uniGroupType"),
        )


@dataclass
class DailyOverview(AulaDataClass):
    overview_id: Optional[int] = None
    institution_profile: Optional[InstitutionProfile] = None
    main_group: Optional[MainGroup] = None
    status_code: Optional[int] = field(init=False) 
    status: Optional[int] = None
    location: Optional[str] = None
    sleep_intervals: List[Any] = dataclasses.field(default_factory=list)
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    exit_with: Optional[str] = None
    comment: Optional[str] = None
    _raw: Optional[dict] = field(default=None, repr=False)

    @property
    def status_text(self) -> str:
        """Returns the human-readable status string based on the status code."""
        from .const import DAILY_OVERVIEW_STATUS_TEXT 
        if self.status_code is not None and 0 <= self.status_code < len(DAILY_OVERVIEW_STATUS_TEXT):
            return DAILY_OVERVIEW_STATUS_TEXT[self.status_code]
        elif self.status_code is not None:
            return f"Unknown Status ({self.status_code})"
        else:
            return "Status N/A"

    @classmethod
    def from_dict(cls, raw_data: dict) -> "DailyOverview":
        """Parses the raw dictionary data (expected list item) into a DailyOverview object."""
        instance = cls(_raw=raw_data) 

        data = raw_data 

        if isinstance(raw_data.get("data"), list) and raw_data["data"]:
            data = raw_data["data"][0] # If it's wrapped in {'data': [overview_dict]}
        else:
            _LOGGER.warning(f"Could not parse DailyOverview from raw data: {raw_data}")
            return instance # Return partially initialized instance

        instance.overview_id = data.get("id")

        inst_profile_data = data.get("institutionProfile")
        if inst_profile_data:
            instance.institution_profile = InstitutionProfile.from_dict(inst_profile_data)

        main_group_data = data.get("mainGroup")
        if main_group_data:
            instance.main_group = MainGroup.from_dict(main_group_data)

        instance.status_code = data.get("status") 
        instance.location = data.get("location")
        instance.sleep_intervals = data.get("sleepIntervals", [])
        instance.check_in_time = data.get("checkInTime")
        instance.check_out_time = data.get("checkOutTime")
        instance.entry_time = data.get("entryTime")
        instance.exit_time = data.get("exitTime")
        instance.exit_with = data.get("exitWith")
        instance.comment = data.get("comment")

        return instance


@dataclass
class Institution(AulaDataClass):
    institution_code: str
    institution_name: str
    _raw: Optional[dict] = field(default=None, repr=False)


@dataclass
class MessageThread(AulaDataClass):
    thread_id: str
    subject: str
    _raw: Optional[dict] = field(default=None, repr=False)


@dataclass
class Message(AulaDataClass):
    id: str
    content_html: str
    _raw: Optional[dict] = field(default=None, repr=False)


@dataclass
class Appointment(AulaDataClass):
    appointment_id: str
    title: str
    _raw: Optional[dict] = field(default=None, repr=False)


@dataclass
class CalendarEvent(AulaDataClass):
    event_id: str
    title: str
    _raw: Optional[dict] = field(default=None, repr=False)
