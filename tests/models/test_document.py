"""Tests for aula.models.document."""

from aula.models.document import SecureDocument


class TestSecureDocument:
    def test_reads_the_portal_fields(self):
        data = {
            "id": 42,
            "title": "Referat",
            "documentType": "Internal",
            "category": "Agenda",
            "createdAt": "2026-01-15T10:00:00+00:00",
            "updatedAt": "2026-01-16T08:00:00+00:00",
            "description": "Fra forældremøde",
            "institutionCode": "280001",
            "creator": {"id": 55, "name": "Medarbejder Et", "alias": False, "metadata": None},
        }

        document = SecureDocument.from_dict(data)

        assert document.id == 42
        assert document.title == "Referat"
        assert document.document_type == "Internal"
        assert document.created_at == "2026-01-15T10:00:00+00:00"
        assert document.updated_at == "2026-01-16T08:00:00+00:00"
        assert document.owner_name == "Medarbejder Et"
        assert document.institution_code == "280001"
