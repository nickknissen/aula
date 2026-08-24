"""Attachments on posts and messages.

Aula sends one attachment shape everywhere: an envelope carrying an id, a
status, its creator, and exactly one of four content variants — a file, a
gallery media item, a link into a cloud drive, or a link to a secure document.
Verified against ``AulaFileResultDto`` in the decompiled mobile app.

The file behind a media item sits one level deeper than a plain file's, so
:class:`Attachment` hoists it: ``attachment.file`` is the file to download
whichever way the attachment arrived, and ``attachment.media`` keeps the
gallery metadata that came with it.
"""

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any

from ..utils.dates import parse_api_datetime
from .base import AulaDataClass
from .institution_profile import InstitutionProfile

_LOGGER = logging.getLogger(__name__)


@dataclass
class AttachmentFile(AulaDataClass):
    """The file behind an attachment."""

    id: int | None = None
    name: str = ""
    url: str | None = None
    created: datetime.datetime | None = None
    scanning_status: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AttachmentFile:
        return cls(
            id=data.get("id"),
            name=data.get("name") or "",
            url=data.get("url"),
            created=parse_api_datetime(data.get("created")),
            scanning_status=data.get("scanningStatus") or "",
            _raw=data,
        )


@dataclass
class AttachmentMedia(AulaDataClass):
    """The gallery metadata Aula adds when an attachment is a media item.

    The media's own file is hoisted onto :attr:`Attachment.file`.
    """

    title: str = ""
    description: str = ""
    media_type: str = ""
    thumbnail_url: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AttachmentMedia:
        return cls(
            title=data.get("title") or "",
            description=data.get("description") or "",
            media_type=data.get("mediaType") or "",
            thumbnail_url=data.get("thumbnailUrl"),
            _raw=data,
        )


@dataclass
class AttachmentLink(AulaDataClass):
    """A link to a file in a cloud drive, attached instead of an upload."""

    service: str = ""
    name: str = ""
    url: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AttachmentLink:
        return cls(
            service=data.get("service") or "",
            name=data.get("name") or "",
            url=data.get("url"),
            _raw=data,
        )


@dataclass
class AttachmentDocument(AulaDataClass):
    """A link to a secure document, which Aula keeps behind its own access check."""

    id: int | None = None
    title: str = ""
    document_type: str = ""
    can_access: bool = False
    is_deleted: bool = False
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AttachmentDocument:
        return cls(
            id=data.get("id"),
            title=data.get("title") or "",
            document_type=data.get("documentType") or "",
            can_access=data.get("canAccess", False),
            is_deleted=data.get("isDeleted", False),
            _raw=data,
        )


@dataclass
class Attachment(AulaDataClass):
    """Something attached to a post or a message.

    :attr:`name` is the attachment's own name, whichever variant it arrived as,
    and :attr:`url` is where its bytes are, so a caller that only wants to name
    or fetch an attachment never has to ask which variant it is.
    """

    id: int | None = None
    name: str = ""
    status: str = ""
    file: AttachmentFile | None = None
    media: AttachmentMedia | None = None
    link: AttachmentLink | None = None
    document: AttachmentDocument | None = None
    creator: InstitutionProfile | None = None
    _raw: dict | None = field(default=None, repr=False)

    @property
    def url(self) -> str | None:
        """Where the attachment's bytes are, or ``None`` for a secure document."""
        if self.file is not None:
            return self.file.url
        if self.link is not None:
            return self.link.url
        return None

    @property
    def created(self) -> datetime.datetime | None:
        """When the attached file was created."""
        return self.file.created if self.file is not None else None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attachment:
        media_data = data.get("media") or {}
        media = AttachmentMedia.from_dict(media_data) if media_data else None

        # A media item wraps its file one level deeper than a plain file.
        file_data = media_data.get("file") or data.get("file") or {}
        file = AttachmentFile.from_dict(file_data) if file_data else None

        link_data = data.get("link") or {}
        link = AttachmentLink.from_dict(link_data) if link_data else None

        document_data = data.get("document") or {}
        document = AttachmentDocument.from_dict(document_data) if document_data else None

        creator_data = data.get("creator") or {}
        creator = InstitutionProfile.from_dict(creator_data) if creator_data else None

        # Most attachments name themselves; the rest are named by their content.
        name = data.get("name") or ""
        if not name:
            if file is not None:
                name = file.name
            elif link is not None:
                name = link.name
            elif document is not None:
                name = document.title

        return cls(
            id=data.get("id"),
            name=name,
            status=data.get("status") or "",
            file=file,
            media=media,
            link=link,
            document=document,
            creator=creator,
            _raw=data,
        )


def parse_attachments(items: Any) -> list[Attachment]:
    """Read an API ``attachments`` list, skipping anything unreadable."""
    attachments: list[Attachment] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            attachments.append(Attachment.from_dict(item))
        except (TypeError, ValueError, KeyError) as e:
            _LOGGER.warning("Skipping attachment due to parsing error: %s - Data: %s", e, item)
    return attachments
