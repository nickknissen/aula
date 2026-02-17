import dataclasses
import datetime
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .utils import html_to_markdown, html_to_plain

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
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Child":
        return cls(
            _raw=data,
            id=data["id"],
            profile_id=data["profileId"],
            name=data["name"],
            institution_name=data.get("institutionProfile", {}).get("institutionName", ""),
            profile_picture=data.get("profilePicture", {}).get("url", ""),
        )


@dataclass
class Profile(AulaDataClass):
    profile_id: int
    display_name: str
    children: list[Child] = field(default_factory=list)
    institution_profile_ids: list[int] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)


@dataclass
class ProfileContext(AulaDataClass):
    _raw: dict | None = field(default=None, repr=False)


@dataclass
class ProfilePicture(AulaDataClass):
    url: str | None = None
    _raw: dict | None = field(default=None, repr=False)


@dataclass
class InstitutionProfile(AulaDataClass):
    profile_id: int | None = None
    id: int | None = None
    institution_code: str | None = None
    institution_name: str | None = None
    role: str | None = None
    name: str | None = None
    profile_picture: ProfilePicture | None = None
    short_name: str | None = None
    institution_role: str | None = None
    metadata: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstitutionProfile":
        pic_data = data.get("profilePicture", {})
        return cls(
            profile_id=data.get("profileId"),
            id=data.get("id"),
            institution_code=data.get("institutionCode"),
            institution_name=data.get("institutionName"),
            role=data.get("role"),
            name=data.get("name"),
            profile_picture=ProfilePicture(url=pic_data.get("url")) if pic_data else None,
            short_name=data.get("shortName"),
            institution_role=data.get("institutionRole"),
            metadata=data.get("metadata"),
        )


@dataclass
class MainGroup(AulaDataClass):
    id: int | None = None
    name: str | None = None
    short_name: str | None = None
    institution_code: str | None = None
    institution_name: str | None = None
    uni_group_type: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MainGroup":
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
    id: int | None = None
    institution_profile: InstitutionProfile | None = None
    main_group: MainGroup | None = None
    status: PresenceState | None = None
    location: str | None = None
    sleep_intervals: list[Any] = dataclasses.field(default_factory=list)
    check_in_time: str | None = None
    check_out_time: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    exit_with: str | None = None
    comment: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, raw_data: dict[str, Any]) -> "DailyOverview":
        status_value = raw_data.get("status")
        presence_status = None
        if status_value is not None:
            try:
                presence_status = PresenceState(status_value)
            except ValueError:
                _LOGGER.warning(f"Unknown presence status value received: {status_value}")

        inst_data = raw_data.get("institutionProfile")
        mg_data = raw_data.get("mainGroup")

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
            institution_profile=(
                InstitutionProfile.from_dict(inst_data) if isinstance(inst_data, dict) else None
            ),
            main_group=MainGroup.from_dict(mg_data) if isinstance(mg_data, dict) else None,
        )


@dataclass
class Institution(AulaDataClass):
    institution_code: str
    institution_name: str
    _raw: dict | None = field(default=None, repr=False)


@dataclass
class MessageThread(AulaDataClass):
    thread_id: str
    subject: str
    _raw: dict | None = field(default=None, repr=False)


@dataclass
class Message(AulaDataClass):
    id: str
    content_html: str
    _raw: dict | None = field(default=None, repr=False)

    @property
    def content(self) -> str:
        """Return the plain text content stripped from HTML."""
        return html_to_plain(self.content_html)

    @property
    def content_markdown(self) -> str:
        """Return the content converted to Markdown format."""
        return html_to_markdown(self.content_html)


@dataclass
class Appointment(AulaDataClass):
    appointment_id: str
    title: str
    _raw: dict | None = field(default=None, repr=False)


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
    profile_picture: dict | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProfileReference":
        return cls(
            id=data["id"],
            profile_id=data["profileId"],
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
    timestamp: datetime.datetime | None
    owner: ProfileReference
    allow_comments: bool
    shared_with_groups: list[dict]
    publish_at: datetime.datetime | None
    is_published: bool
    expire_at: datetime.datetime | None
    is_expired: bool
    is_important: bool
    important_from: datetime.datetime | None
    important_to: datetime.datetime | None
    attachments: list[dict]
    comment_count: int
    can_current_user_delete: bool
    can_current_user_comment: bool
    edited_at: datetime.datetime | None = None
    _raw: dict | None = field(default=None, repr=False)

    @property
    def content(self) -> str:
        """Return the plain text content stripped from HTML."""
        return html_to_plain(self.content_html)

    @property
    def content_markdown(self) -> str:
        """Return the content converted to Markdown format."""
        return html_to_markdown(self.content_html)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Post":
        """Create a Post instance from API response data."""

        def parse_datetime(dt_str: str | None) -> datetime.datetime | None:
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
            id=data["id"],
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
    teacher_name: str | None
    has_substitute: bool
    substitute_name: str | None
    location: str | None
    belongs_to: int | None
    _raw: dict | None = field(default=None, repr=False)
