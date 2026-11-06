"""Tests for aula.models.common_file."""

from aula.models.common_file import CommonFile

COMMON_FILE = {
    "id": 501,
    "title": "Ordensregler",
    "created": "2026-08-01T08:00:00+00:00",
    "institution": {"institutionCode": "280001", "name": "Eksempel Skole"},
    "isDataPolicy": False,
    "groupRestrictions": [],
    "profileTypeRestrictions": ["guardian"],
    "file": {
        "id": 9,
        "name": "ordensregler.pdf",
        "status": "available",
        "creator": {"profileId": 1, "id": 2, "name": "Medarbejder Et"},
        "file": {
            "id": 10,
            "bucket": "bucket",
            "key": "key",
            "url": "https://example.com/1",
            "created": "2026-08-01T08:00:00+00:00",
            "name": "ordensregler.pdf",
            "scanningStatus": "available",
        },
        "link": None,
        "media": None,
        "document": None,
        "currentUserCanReport": False,
    },
}


class TestCommonFile:
    def test_from_dict(self):
        common_file = CommonFile.from_dict(COMMON_FILE)

        assert common_file.id == 501
        assert common_file.title == "Ordensregler"
        assert common_file.created_at == "2026-08-01T08:00:00+00:00"
        assert common_file.institution_code == "280001"
        assert common_file.institution_name == "Eksempel Skole"
        assert common_file.file_name == "ordensregler.pdf"
        assert common_file.file_url == "https://example.com/1"
        assert common_file.is_data_policy is False
        assert common_file._raw is COMMON_FILE

    def test_from_dict_without_file_or_institution(self):
        common_file = CommonFile.from_dict({"id": 7, "title": "Link", "file": None})

        assert common_file.file_name == ""
        assert common_file.file_url == ""
        assert common_file.institution_name == ""

    def test_dict_conversion_leaves_out_raw(self):
        result = dict(CommonFile.from_dict(COMMON_FILE))

        assert result["file_url"] == "https://example.com/1"
        assert "_raw" not in result
