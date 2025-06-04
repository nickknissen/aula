import dataclasses
import datetime
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

import html2text

# Logger
_LOGGER = logging.getLogger(__name__)


class PresenceState(Enum):
    NOT_PRESENT = 0  # Ikke kommet
    SICK = 1  # Syg
    REPORTED_ABSENT = 2  # Ferie/fri
    PRESENT = 3  # Til stede
    FIELDTRIP = 4  # På tur
    SLEEPING = 5  # Sover
    SPARE_TIME_ACTIVITY = 6  # Til aktivitet
    PHYSICAL_PLACEMENT = 7  # Fysisk placering
    CHECKED_OUT = 8  # Gået

    @classmethod
    def get_display_name(cls, value: int) -> str:
        """Return a user-friendly display name for the status value."""
        try:
            member = cls(value)
            # Replace underscores with spaces and capitalize words for display
            return member.name.replace("_", " ").title()
        except ValueError:
            return "Unknown Status"


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
    institution_name: str
    profile_picture: str
    _raw: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Child":
        return cls(
            _raw=data,
            id=data.get("id"),
            profile_id=data.get("profileId"),
            name=data.get("name"),
            institution_name=data.get("institutionProfile").get("institutionName"),
            profile_picture=data.get("profilePicture", {}).get("url"),
        )


@dataclass
class Profile(AulaDataClass):
    profile_id: int
    display_name: str
    children: List[Child] = field(default_factory=list)
    institution_profile_ids: List[int] = field(default_factory=list)
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
    status: Optional[PresenceState] = None
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
        status_value = raw_data.get("status")
        presence_status = None
        if status_value is not None:
            try:
                presence_status = PresenceState(status_value)
            except ValueError:
                _LOGGER.warning(
                    f"Unknown presence status value received: {status_value}"
                )

        return cls(
            id=raw_data.get("id"),
            status=presence_status,
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
class ProfileReference(AulaDataClass):
    """Represents a reference to a profile in Aula."""

    id: int
    profile_id: int
    first_name: str
    last_name: str
    full_name: str
    short_name: str
    role: str
    institution_name: str
    profile_picture: Optional[dict] = None
    _raw: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileReference":
        return cls(
            id=data.get("id"),
            profile_id=data.get("profileId"),
            first_name=data.get("firstName", ""),
            last_name=data.get("lastName", ""),
            full_name=data.get("fullName", ""),
            short_name=data.get("shortName", ""),
            role=data.get("role", ""),
            institution_name=data.get("institution", {}).get("institutionName", ""),
            profile_picture=data.get("profilePicture"),
            _raw=data,
        )


@dataclass
class Post(AulaDataClass):
    """Represents a post in Aula (news, announcements, etc.)."""

    id: int
    title: str
    content_html: str
    timestamp: datetime.datetime
    owner: ProfileReference
    allow_comments: bool
    shared_with_groups: List[dict]
    publish_at: Optional[datetime.datetime]
    is_published: bool
    expire_at: Optional[datetime.datetime]
    is_expired: bool
    is_important: bool
    important_from: Optional[datetime.datetime]
    important_to: Optional[datetime.datetime]
    attachments: List[dict]
    comment_count: int
    can_current_user_delete: bool
    can_current_user_comment: bool
    edited_at: Optional[datetime.datetime] = None
    _raw: Optional[dict] = field(default=None, repr=False)

    @property
    def content(self) -> str:
        """Return the plain text content stripped from HTML."""
        if not self.content_html:
            return ""
        try:
            h = html2text.HTML2Text()
            h.ignore_links = True
            h.ignore_images = True
            h.ignore_tables = True
            return h.handle(self.content_html).strip()
        except Exception as e:
            _LOGGER.warning(f"Error converting post content to plain text: {e}")
            return self.content_html

    @property
    def content_markdown(self) -> str:
        """Return the content converted to Markdown format."""
        if not self.content_html:
            return ""
        try:
            h = html2text.HTML2Text()
            return h.handle(self.content_html).strip()
        except Exception as e:
            _LOGGER.warning(f"Error converting post content to Markdown: {e}")
            return self.content_html

    @classmethod
    def from_dict(cls, data: dict) -> "Post":
        """Create a Post instance from API response data."""

        def parse_datetime(dt_str: Optional[str]) -> Optional[datetime.datetime]:
            if not dt_str:
                return None
            try:
                # Handle timezone offset
                if dt_str.endswith("Z"):
                    dt_str = dt_str[:-1] + "+00:00"
                return datetime.datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                return None

        owner = ProfileReference.from_dict(data.get("ownerProfile", {}))

        return cls(
            id=data.get("id"),
            title=data.get("title", ""),
            content_html=data.get("content", {}).get("html", ""),
            timestamp=parse_datetime(data.get("timestamp")),
            owner=owner,
            allow_comments=data.get("allowComments", False),
            shared_with_groups=data.get("sharedWithGroups", []),
            publish_at=parse_datetime(data.get("publishAt")),
            is_published=data.get("isPublished", False),
            expire_at=parse_datetime(data.get("expireAt")),
            is_expired=data.get("isExpired", False),
            is_important=data.get("isImportant", False),
            important_from=parse_datetime(data.get("importantFrom")),
            important_to=parse_datetime(data.get("importantTo")),
            attachments=data.get("attachments", []),
            comment_count=data.get("commentCount", 0),
            can_current_user_delete=data.get("canCurrentUserDelete", False),
            can_current_user_comment=data.get("canCurrentUserComment", False),
            edited_at=parse_datetime(data.get("editedAt")),
            _raw=data,
        )


@dataclass
class CalendarEvent(AulaDataClass):
    id: int
    title: str
    start_datetime: datetime.datetime
    end_datetime: datetime.datetime
    teacher_name: str
    has_substitute: bool
    substitute_name: Optional[str]
    location: Optional[str]
    belongs_to: int
    _raw: Optional[dict] = field(default=None, repr=False)
