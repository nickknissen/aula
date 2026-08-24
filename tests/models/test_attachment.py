"""Tests for aula.models.attachment."""

import datetime

from aula.models.attachment import Attachment, parse_attachments

# A gallery photo attached to a post: Aula wraps the file in a "media" object.
MEDIA_ATTACHMENT = {
    "id": 5001,
    "status": "AVAILABLE",
    "creator": {
        "id": 200,
        "profileId": 300,
        "name": "Teacher One",
        "shortName": "TEA",
        "role": "employee",
        "institutionCode": "A1234",
        "institutionName": "Example School",
    },
    "media": {
        "title": "Class outing",
        "description": "On the bus",
        "mediaType": "image",
        "thumbnailUrl": "https://files.example.test/thumb.jpg",
        "file": {
            "id": 9001,
            "name": "outing.jpg",
            "url": "https://files.example.test/outing.jpg",
            "created": "2026-03-01T09:30:00Z",
            "scanningStatus": "Available",
        },
    },
}

# A file attached to a message: the file sits directly on the attachment.
FILE_ATTACHMENT = {
    "id": 5002,
    "status": "AVAILABLE",
    "file": {
        "id": 9002,
        "name": "weekplan.pdf",
        "url": "https://files.example.test/weekplan.pdf",
        "created": "2026-03-02T11:00:00+01:00",
        "scanningStatus": "Available",
    },
}


def test_attachment_from_dict_media():
    attachment = Attachment.from_dict(MEDIA_ATTACHMENT)

    assert attachment.id == 5001
    assert attachment.status == "AVAILABLE"
    assert attachment.name == "outing.jpg"
    assert attachment.url == "https://files.example.test/outing.jpg"
    assert attachment.created == datetime.datetime(2026, 3, 1, 9, 30, tzinfo=datetime.UTC)
    assert attachment.file is not None
    assert attachment.file.id == 9001
    assert attachment.file.name == "outing.jpg"
    assert attachment.file.scanning_status == "Available"
    assert attachment.media is not None
    assert attachment.media.title == "Class outing"
    assert attachment.media.description == "On the bus"
    assert attachment.media.media_type == "image"
    assert attachment.media.thumbnail_url == "https://files.example.test/thumb.jpg"
    assert attachment.creator is not None
    assert attachment.creator.name == "Teacher One"
    assert attachment.creator.institution_name == "Example School"
    assert attachment._raw is MEDIA_ATTACHMENT


def test_attachment_from_dict_file():
    """A message attachment carries its file directly, and reads the same way."""
    attachment = Attachment.from_dict(FILE_ATTACHMENT)

    assert attachment.id == 5002
    assert attachment.name == "weekplan.pdf"
    assert attachment.url == "https://files.example.test/weekplan.pdf"
    assert attachment.created is not None
    assert attachment.created.hour == 11
    assert attachment.media is None
    assert attachment.creator is None


def test_attachment_names_itself():
    """Aula names most attachments itself, and that name wins over the file's."""
    attachment = Attachment.from_dict(
        {
            "id": 5008,
            "name": "Week plan, week 34.pdf",
            "status": "available",
            "file": {"name": "uge-34.pdf", "url": "https://files.example.test/uge-34.pdf"},
        }
    )

    assert attachment.name == "Week plan, week 34.pdf"
    assert attachment.file is not None
    assert attachment.file.name == "uge-34.pdf"


def test_attachment_from_dict_missing_fields():
    attachment = Attachment.from_dict({"id": 5003})

    assert attachment.id == 5003
    assert attachment.name == ""
    assert attachment.status == ""
    assert attachment.file is None
    assert attachment.media is None
    assert attachment.link is None
    assert attachment.document is None
    assert attachment.creator is None
    assert attachment.url is None
    assert attachment.created is None


def test_attachment_from_dict_null_nested_objects():
    """Aula sends an explicit null for the variants an attachment is not."""
    attachment = Attachment.from_dict(
        {"id": 5004, "file": None, "media": None, "link": None, "document": None, "creator": None}
    )

    assert attachment.file is None
    assert attachment.media is None
    assert attachment.name == ""
    assert attachment.url is None


def test_attachment_from_dict_link():
    attachment = Attachment.from_dict(
        {
            "id": 5005,
            "status": "AVAILABLE",
            "link": {
                "service": "OneDrive",
                "name": "Parent meeting slides",
                "url": "https://links.example.test/slides",
            },
        }
    )

    assert attachment.name == "Parent meeting slides"
    assert attachment.url == "https://links.example.test/slides"
    assert attachment.link is not None
    assert attachment.link.service == "OneDrive"
    assert attachment.file is None


def test_attachment_from_dict_document():
    attachment = Attachment.from_dict(
        {
            "id": 5006,
            "document": {
                "id": 77,
                "title": "House rules",
                "documentType": "secure",
                "canAccess": True,
                "isDeleted": False,
            },
        }
    )

    assert attachment.name == "House rules"
    assert attachment.url is None
    assert attachment.document is not None
    assert attachment.document.id == 77
    assert attachment.document.document_type == "secure"
    assert attachment.document.can_access is True
    assert attachment.document.is_deleted is False


def test_attachment_from_dict_unreadable_created():
    attachment = Attachment.from_dict({"id": 5007, "file": {"name": "x.pdf", "created": "soon"}})

    assert attachment.created is None
    assert attachment.name == "x.pdf"


def test_attachment_dict_conversion():
    result = dict(Attachment.from_dict(MEDIA_ATTACHMENT))

    assert result["id"] == 5001
    assert result["name"] == "outing.jpg"
    assert result["file"]["url"] == "https://files.example.test/outing.jpg"
    assert result["media"]["title"] == "Class outing"
    assert result["creator"]["name"] == "Teacher One"
    assert "_raw" not in result
    assert "_raw" not in result["file"]


def test_parse_attachments_reads_every_item():
    attachments = parse_attachments([MEDIA_ATTACHMENT, FILE_ATTACHMENT])

    assert [a.name for a in attachments] == ["outing.jpg", "weekplan.pdf"]


def test_parse_attachments_skips_unreadable_items():
    attachments = parse_attachments([MEDIA_ATTACHMENT, "not-a-dict", None])

    assert [a.name for a in attachments] == ["outing.jpg"]


def test_parse_attachments_of_nothing():
    assert parse_attachments(None) == []
    assert parse_attachments([]) == []
