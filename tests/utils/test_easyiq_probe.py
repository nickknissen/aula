"""Tests for aula.utils.easyiq_probe."""

from unittest.mock import AsyncMock, Mock

import pytest

from aula.const import EASYIQ_CALENDAR_PATH, EASYIQ_HOMEWORK_PATH
from aula.utils.easyiq_probe import (
    Attempt,
    ChildProbe,
    ProbeReport,
    _describe_rows,
    _match_easyiq_entry,
    probe_easyiq,
    render_report,
)


class TestDescribeRows:
    def test_bare_list(self):
        rows, histogram, keys = _describe_rows([{"itemType": 4}, {"itemType": 9}, {"itemType": 4}])
        assert rows == 3
        assert histogram == {"4": 2, "9": 1}
        assert keys == ["itemType"]

    def test_wrapped_list(self):
        rows, histogram, _ = _describe_rows({"events": [{"ItemType": 4}]})
        assert rows == 1
        assert histogram == {"4": 1}

    def test_item_type_casing_does_not_split_the_histogram(self):
        _, histogram, _ = _describe_rows([{"ItemType": 4}, {"itemType": 4}])
        assert histogram == {"4": 2}

    def test_keys_keep_their_original_casing(self):
        """The casing is the finding, so it must survive into the report."""
        _, _, keys = _describe_rows([{"ItemType": 4, "Courses": "x"}])
        assert keys == ["ItemType", "Courses"]

    def test_missing_item_type(self):
        _, histogram, _ = _describe_rows([{"courses": "x"}])
        assert histogram == {"missing": 1}

    def test_non_list_payload(self):
        assert _describe_rows(None) == (None, {}, [])


class TestMatchEasyIQEntry:
    AULA = {"institution_profile_id": "4242", "profile_id": "77", "user_id": "astr8360"}

    def test_matches_by_login_and_reports_the_equal_id(self):
        found, matches = _match_easyiq_entry(
            [{"Id": "4242", "Login": "astr8360", "Name": "A"}], self.AULA
        )
        assert found is True
        assert matches == ["institution_profile_id"]

    def test_entry_with_an_id_of_its_own(self):
        """This is the case that would break the loginId assumption."""
        found, matches = _match_easyiq_entry(
            [{"Id": "99999", "Login": "astr8360", "Name": "A"}], self.AULA
        )
        assert found is True
        assert matches == []

    def test_child_absent_from_easyiq(self):
        found, matches = _match_easyiq_entry([{"Id": "1", "Login": "other"}], self.AULA)
        assert found is False
        assert matches == []

    def test_no_entries(self):
        assert _match_easyiq_entry([], self.AULA) == (False, [])


class TestRenderReport:
    def _report(self) -> ProbeReport:
        return ProbeReport(
            widgets=[("0142", "EasyIQ Lektier", "iframe")],
            tokens={"0128": "ok", "0142": "ok"},
            children_status=200,
            children_count=1,
            children_fields=["Id", "Login", "Name"],
            children=[
                ChildProbe(
                    label="Child 1 of 2",
                    easyiq_entry_found=True,
                    easyiq_id_matches=["institution_profile_id"],
                    attempts={
                        EASYIQ_HOMEWORK_PATH: [
                            Attempt(
                                login_id_source="institution_profile_id",
                                child_header_source="user_id",
                                status=200,
                                rows=3,
                                item_types={"4": 3},
                                keys=["ItemType", "Courses"],
                                body=[{"Courses": "Dansk"}],
                            )
                        ]
                    },
                )
            ],
        )

    def test_reports_the_findings(self):
        text = "\n".join(render_report(self._report()))
        assert "EasyIQ Lektier" in text
        assert "EasyIQ Id equals the Aula institution_profile_id" in text
        assert "loginId=institution_profile_id child=user_id  200  3 rows" in text
        assert "keys: ItemType, Courses" in text

    def test_leaks_no_values_by_default(self):
        text = "\n".join(render_report(self._report()))
        assert "Dansk" not in text
        assert "4242" not in text
        assert "astr8360" not in text
        assert "No names, subjects or IDs are included" in text

    def test_include_values_prints_bodies_and_warns(self):
        text = "\n".join(render_report(self._report(), include_values=True))
        assert "Dansk" in text
        assert "Do not paste this publicly" in text

    def test_child_not_on_easyiq(self):
        report = self._report()
        report.children[0].easyiq_entry_found = False
        assert "likely not an EasyIQ institution" in "\n".join(render_report(report))

    def test_error_is_shown(self):
        report = self._report()
        report.children[0].attempts[EASYIQ_HOMEWORK_PATH][0].error = "AulaServerError: HTTP 500"
        assert "AulaServerError: HTTP 500" in "\n".join(render_report(report))


class TestProbeEasyIQ:
    @pytest.fixture
    def child(self):
        child = Mock()
        child.id = 4242
        child.profile_id = 77
        child._raw = {"userId": "astr8360"}
        return child

    def _widget(self, widget_id, name, widget_type, supplier):
        # ``name`` is reserved by Mock's constructor, so it has to be set after.
        widget = Mock(widget_id=widget_id, widget_type=widget_type, widget_supplier=supplier)
        widget.name = name
        return widget

    def _client(self, responses):
        client = Mock()
        client.get_widgets = AsyncMock(
            return_value=[
                self._widget("0142", "EasyIQ Lektier", "iframe", "EasyIQ"),
                self._widget("0019", "Biblioteket", "secure", "Systematic"),
            ]
        )
        client.widgets = Mock()
        client.widgets._get_bearer_token = AsyncMock(return_value="Bearer t")
        client.widgets.easyiq_headers = Mock(return_value={"Authorization": "Bearer t"})
        client.widgets.easyiq_identifier_variants = Mock(return_value=[("4242", "astr8360")])
        client._request_with_version_retry = AsyncMock(side_effect=responses)
        return client

    def _resp(self, status, payload):
        resp = Mock()
        resp.status_code = status
        resp.json = Mock(return_value=payload)
        return resp

    @pytest.mark.asyncio
    async def test_probes_both_controllers_and_keeps_only_easyiq_widgets(self, child):
        client = self._client(
            [
                self._resp(200, {"Children": [{"Id": "4242", "Login": "astr8360"}]}),
                self._resp(200, [{"itemType": 9}]),
                self._resp(200, [{"ItemType": 4}]),
            ]
        )

        report = await probe_easyiq(client, [child], "nick536a", "2026-08-10T00:00:00Z")

        assert report.widgets == [("0142", "EasyIQ Lektier", "iframe")]
        assert report.children_count == 1
        probe = report.children[0]
        assert probe.easyiq_id_matches == ["institution_profile_id"]
        assert probe.attempts[EASYIQ_CALENDAR_PATH][0].item_types == {"9": 1}
        assert probe.attempts[EASYIQ_HOMEWORK_PATH][0].item_types == {"4": 1}
        assert probe.attempts[EASYIQ_HOMEWORK_PATH][0].keys == ["ItemType"]

    @pytest.mark.asyncio
    async def test_a_failing_controller_is_recorded_not_raised(self, child):
        client = self._client(
            [
                self._resp(200, {"Children": []}),
                Exception("boom"),
                self._resp(200, []),
            ]
        )

        report = await probe_easyiq(client, [child], "nick536a", "2026-08-10T00:00:00Z")

        assert "boom" in report.children[0].attempts[EASYIQ_CALENDAR_PATH][0].error
        assert report.children[0].attempts[EASYIQ_HOMEWORK_PATH][0].status == 200

    @pytest.mark.asyncio
    async def test_bodies_are_only_captured_when_asked_for(self, child):
        responses = [
            self._resp(200, {"Children": []}),
            self._resp(200, [{"a": 1}]),
            self._resp(200, []),
        ]
        client = self._client(list(responses))
        report = await probe_easyiq(client, [child], "nick536a", "2026-08-10T00:00:00Z")
        assert report.children[0].attempts[EASYIQ_CALENDAR_PATH][0].body is None

        client = self._client(list(responses))
        report = await probe_easyiq(
            client, [child], "nick536a", "2026-08-10T00:00:00Z", include_values=True
        )
        assert report.children[0].attempts[EASYIQ_CALENDAR_PATH][0].body == [{"a": 1}]
