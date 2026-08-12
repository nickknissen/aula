"""Tests for aula.models.vacation_registration."""

from aula.models.vacation_registration import VacationRegistration


class TestVacationRegistration:
    def test_from_dict_full(self):
        data = {
            "vacationRegistrationId": 9911,
            "title": "Sommerferie",
            "startDate": "2026-07-01",
            "endDate": "2026-07-14",
            "responseId": 4455,
            "responseDeadline": "2026-06-01",
            "noteToGuardian": "Husk at svare",
            "isEditable": True,
            "isMissingAnswer": True,
            "isPresenceTimesRequired": True,
        }
        child = {"id": 4727534, "name": "Anna", "institutionCode": "G19736", "metadata": "0.A"}

        reg = VacationRegistration.from_dict(data, child)

        assert reg.id == 9911
        assert reg.child_id == 4727534
        assert reg.child_name == "Anna"
        assert reg.title == "Sommerferie"
        assert reg.start_date == "2026-07-01"
        assert reg.end_date == "2026-07-14"
        assert reg.response_id == 4455
        assert reg.response_deadline == "2026-06-01"
        assert reg.note_to_guardian == "Husk at svare"
        assert reg.is_editable is True
        assert reg.is_missing_answer is True
        assert reg.is_presence_times_required is True
        assert reg._raw is data

    def test_from_dict_minimal(self):
        reg = VacationRegistration.from_dict({})

        assert reg.id == 0
        assert reg.child_id == 0
        assert reg.child_name == ""
        assert reg.start_date is None
        assert reg.end_date is None
        assert reg.response_deadline is None
        assert reg.is_missing_answer is False

    def test_from_dict_without_child(self):
        reg = VacationRegistration.from_dict({"vacationRegistrationId": 7})

        assert reg.id == 7
        assert reg.child_id == 0
        assert reg.child_name == ""

    def test_from_dict_null_note_becomes_empty_string(self):
        reg = VacationRegistration.from_dict({"noteToGuardian": None})

        assert reg.note_to_guardian == ""
