"""Tests for aula.models.presence_registration."""

from aula.models.presence import (
    PresenceDashboard,
    PresenceModule,
    PresenceModulePermission,
    PresenceState,
)
from aula.models.presence_registration import (
    ChildPresenceState,
    PresenceActivity,
    PresenceConfiguration,
    PresenceDay,
    PresenceRegistration,
    PresenceRegistrationDetail,
    PresenceWeekOverview,
)


class TestPresenceRegistration:
    def test_from_dict_full(self):
        data = {
            "id": 1,
            "institutionProfileId": 201,
            "status": 3,
            "date": "2026-03-08",
            "entryTime": "08:00",
            "exitTime": "15:00",
            "checkInTime": "07:55",
            "checkOutTime": "15:05",
        }
        reg = PresenceRegistration.from_dict(data)
        assert reg.id == 1
        assert reg.institution_profile_id == 201
        assert reg.status == PresenceState.PRESENT
        assert reg.date == "2026-03-08"
        assert reg.entry_time == "08:00"
        assert reg.exit_time == "15:00"
        assert reg.check_in_time == "07:55"
        assert reg.check_out_time == "15:05"
        assert reg._raw is data

    def test_from_dict_minimal(self):
        reg = PresenceRegistration.from_dict({})
        assert reg.id is None
        assert reg.status is None

    def test_from_dict_unknown_status(self):
        reg = PresenceRegistration.from_dict({"status": 99})
        assert reg.status is None


class TestPresenceRegistrationDetail:
    def test_from_dict_full(self):
        data = {
            "id": 555,
            "childName": "Maja",
            "institutionProfileId": 201,
            "status": 1,
            "date": "2026-03-08",
            "entryTime": "08:00",
            "exitTime": "15:00",
            "checkInTime": "07:55",
            "checkOutTime": None,
            "exitWith": "Mor",
            "comment": "Halvdag",
        }
        detail = PresenceRegistrationDetail.from_dict(data)
        assert detail.id == 555
        assert detail.child_name == "Maja"
        assert detail.status == PresenceState.SICK
        assert detail.exit_with == "Mor"
        assert detail.comment == "Halvdag"

    def test_from_dict_minimal(self):
        detail = PresenceRegistrationDetail.from_dict({})
        assert detail.child_name is None


class TestChildPresenceState:
    def test_from_dict_api_format(self):
        """Real API uses 'state' and nests profile info in 'uniStudent'."""
        data = {
            "uniStudentId": 201,
            "uniStudent": {"id": 201, "name": "Maja"},
            "state": 3,
        }
        state = ChildPresenceState.from_dict(data)
        assert state.institution_profile_id == 201
        assert state.name == "Maja"
        assert state.status == PresenceState.PRESENT

    def test_from_dict_fallback_format(self):
        """Fallback: flat format with 'status' and 'institutionProfileId'."""
        data = {"institutionProfileId": 201, "status": 2}
        state = ChildPresenceState.from_dict(data)
        assert state.institution_profile_id == 201
        assert state.status == PresenceState.REPORTED_ABSENT

    def test_from_dict_unknown_status(self):
        state = ChildPresenceState.from_dict({"state": 42})
        assert state.status is None


class TestPresenceConfiguration:
    def test_from_dict_api_format(self):
        data = {
            "uniStudentId": 201,
            "presenceConfiguration": {
                "institution": {"institutionCode": "G19736", "name": "Test School"},
                "pickup": True,
                "goHomeWith": True,
                "selfDecider": False,
            },
        }
        config = PresenceConfiguration.from_dict(data)
        assert config.child_id == 201
        assert config.institution_code == "G19736"
        assert config.institution_name == "Test School"
        assert config.pickup is True
        assert config.go_home_with is True
        assert config.self_decider is False

    def test_from_dict_minimal(self):
        config = PresenceConfiguration.from_dict({})
        assert config.child_id is None
        assert config.pickup is None


class TestPresenceConfigurationModulePermissions:
    """Module permissions gate the presence writes, per dashboard."""

    @staticmethod
    def _config(*dashboards: dict) -> PresenceConfiguration:
        return PresenceConfiguration.from_dict(
            {
                "uniStudentId": 201,
                "presenceConfiguration": {"dashboardModuleSettings": list(dashboards)},
            }
        )

    def test_reads_guardian_permissions(self):
        config = self._config(
            {
                "presenceDashboardContext": "guardian_dashboard",
                "presenceModules": [
                    {"moduleType": "report_sick", "permission": "editable"},
                    {"moduleType": "vacation", "permission": "readable"},
                ],
            }
        )
        assert config.permission(PresenceModule.REPORT_SICK) is PresenceModulePermission.EDITABLE
        assert config.can_edit(PresenceModule.REPORT_SICK) is True
        assert config.permission(PresenceModule.VACATION) is PresenceModulePermission.READABLE
        assert config.can_edit(PresenceModule.VACATION) is False

    def test_readable_and_deactivated_are_not_editable(self):
        for permission in ("readable", "deactivated"):
            config = self._config(
                {
                    "presenceDashboardContext": "guardian_dashboard",
                    "presenceModules": [{"moduleType": "report_sick", "permission": permission}],
                }
            )
            assert config.can_edit(PresenceModule.REPORT_SICK) is False

    def test_employee_permission_does_not_grant_guardian_access(self):
        """Permissions are per dashboard; the guardian check must not read another."""
        config = self._config(
            {
                "presenceDashboardContext": "employee_dashboard",
                "presenceModules": [{"moduleType": "report_sick", "permission": "editable"}],
            }
        )
        assert config.can_edit(PresenceModule.REPORT_SICK) is False
        assert config.can_edit(PresenceModule.REPORT_SICK, PresenceDashboard.EMPLOYEE) is True

    def test_missing_module_reports_none_rather_than_denial(self):
        config = self._config(
            {
                "presenceDashboardContext": "guardian_dashboard",
                "presenceModules": [{"moduleType": "vacation", "permission": "editable"}],
            }
        )
        assert config.permission(PresenceModule.REPORT_SICK) is None
        assert config.can_edit(PresenceModule.REPORT_SICK) is False

    def test_unknown_permission_string_is_not_editable(self):
        """A permission Aula adds later must not be read as granted."""
        config = self._config(
            {
                "presenceDashboardContext": "guardian_dashboard",
                "presenceModules": [{"moduleType": "report_sick", "permission": "future_value"}],
            }
        )
        assert config.permission(PresenceModule.REPORT_SICK) is None
        assert config.can_edit(PresenceModule.REPORT_SICK) is False

    def test_unknown_module_is_preserved_and_readable_by_name(self):
        config = self._config(
            {
                "presenceDashboardContext": "guardian_dashboard",
                "presenceModules": [{"moduleType": "future_module", "permission": "editable"}],
            }
        )
        assert config.module_permissions["guardian_dashboard"]["future_module"] == "editable"
        assert config.can_edit("future_module") is True

    def test_malformed_settings_are_skipped(self):
        config = PresenceConfiguration.from_dict(
            {
                "presenceConfiguration": {
                    "dashboardModuleSettings": [
                        "not-a-dict",
                        {"presenceModules": [{"moduleType": "report_sick"}]},
                        {"presenceDashboardContext": "guardian_dashboard", "presenceModules": None},
                        {
                            "presenceDashboardContext": "guardian_dashboard",
                            "presenceModules": ["nope", {"permission": "editable"}],
                        },
                    ]
                }
            }
        )
        assert config.module_permissions == {"guardian_dashboard": {}}
        assert config.can_edit(PresenceModule.REPORT_SICK) is False

    def test_absent_settings_leave_permissions_empty(self):
        config = PresenceConfiguration.from_dict({"uniStudentId": 201})
        assert config.module_permissions == {}
        assert config.permission(PresenceModule.REPORT_SICK) is None


class TestPresenceWeekOverview:
    def test_from_dict(self):
        data = {
            "days": [
                {
                    "date": "2026-03-02",
                    "activities": [
                        {"title": "Matematik", "startTime": "08:00", "endTime": "09:00"},
                        {"title": "Dansk", "startTime": "09:15", "endTime": "10:15"},
                    ],
                },
                {"date": "2026-03-03", "activities": []},
            ]
        }
        overview = PresenceWeekOverview.from_dict(data)
        assert len(overview.days) == 2
        assert overview.days[0].date == "2026-03-02"
        assert len(overview.days[0].activities) == 2
        assert overview.days[0].activities[0].title == "Matematik"
        assert overview.days[0].activities[0].start_time == "08:00"
        assert overview.days[1].activities == []

    def test_from_dict_empty(self):
        overview = PresenceWeekOverview.from_dict({})
        assert overview.days == []


class TestPresenceActivity:
    def test_from_dict(self):
        act = PresenceActivity.from_dict({"title": "Gym", "startTime": "10:00", "endTime": "11:00"})
        assert act.title == "Gym"
        assert act.start_time == "10:00"
        assert act.end_time == "11:00"


class TestPresenceDay:
    def test_from_dict_skips_none_activities(self):
        data = {
            "date": "2026-03-02",
            "activities": [None, {"title": "Art"}],
        }
        day = PresenceDay.from_dict(data)
        assert len(day.activities) == 1
        assert day.activities[0].title == "Art"
