import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

import html2text

from .const import DAILY_OVERVIEW_STATUS_TEXT

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
        return cls(
            _raw=data,
            id=data.get("id"),
            profile_id=data.get("profileId"),
            name=data.get("name"),
            institution_code=data.get("institutionCode"),
            profile_picture=data.get("profilePicture", {}).get("url"),
        )


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
    id: Optional[int] = None
    institution_profile: Optional[InstitutionProfile] = None
    main_group: Optional[MainGroup] = None
    status: Optional[int] = None
    status_text: Optional[str] = None
    location: Optional[str] = None
    sleep_intervals: List[Any] = dataclasses.field(default_factory=list)
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    exit_with: Optional[str] = None
    comment: Optional[str] = None
    _raw: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, raw_data: dict) -> "DailyOverview":
        return cls(
            id=raw_data.get("id"),
            status=raw_data.get("status"),
            status_text=DAILY_OVERVIEW_STATUS_TEXT[raw_data.get("status")],
            location=raw_data.get("location"),
            sleep_intervals=raw_data.get("sleepIntervals", []),
            check_in_time=raw_data.get("checkInTime"),
            check_out_time=raw_data.get("checkOutTime"),
            entry_time=raw_data.get("entryTime"),
            exit_time=raw_data.get("exitTime"),
            exit_with=raw_data.get("exitWith"),
            comment=raw_data.get("comment"),
            institution_profile=InstitutionProfile.from_dict(
                raw_data.get("institutionProfile")
            ),
            main_group=MainGroup.from_dict(raw_data.get("mainGroup")),
        )


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

    @property
    def content(self) -> str:
        """Return the plain text content stripped from HTML."""
        if not self.content_html:
            return ""
        try:
            h = html2text.HTML2Text()
            h.images_to_alt = True
            h.single_line_break = True
            h.ignore_emphasis = True
            h.ignore_links = True
            h.ignore_tables = True
            markdown = h.handle(self.content_html)
            return markdown.strip()
        except Exception as e:
            _LOGGER.warning(f"Error parsing HTML content for message {self.id}: {e}")
            return self.content_html  # Fallback to raw HTML if parsing fails

    @property
    def content_markdown(self) -> str:
        """Return the content converted to Markdown format."""
        if not self.content_html:
            return ""
        try:
            h = html2text.HTML2Text()
            # Configure html2text options if needed, e.g.:
            # h.ignore_links = True
            # h.ignore_images = True
            markdown = h.handle(self.content_html)
            return markdown.strip()
        except Exception as e:
            _LOGGER.warning(
                f"Error converting HTML to Markdown for message {self.id}: {e}"
            )
            return self.content_html  # Fallback to raw HTML if conversion fails


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
