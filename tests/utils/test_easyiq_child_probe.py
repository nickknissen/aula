"""Tests for aula.utils.easyiq_child_probe."""

from unittest.mock import AsyncMock, Mock

import pytest

from aula.const import EASYIQ_CALENDAR_PATH, EASYIQ_PORTAL
from aula.utils.easyiq_child_probe import (
    ChildProbeReport,
    ChildRequestReport,
    probe_easyiq_children,
    render_child_report,
)

CALENDAR_URL = f"{EASYIQ_PORTAL}{EASYIQ_CALENDAR_PATH}"


def _child(user_id: str, institution_profile_id: int = 4242) -> Mock:
    child = Mock()
    child.id = institution_profile_id
    child._raw = {"userId": user_id}
    return child


def _resp(status: int, payload) -> Mock:
    resp = Mock()
    resp.status_code = status
    resp.raise_for_status = Mock()
    resp.json = Mock(return_value=payload)
    return resp


def _client(responses, *, easyiq_ids: dict[str, str] | None = None) -> Mock:
    easyiq_ids = easyiq_ids or {}
    client = Mock()
    client.widgets = Mock()
    client.widgets._get_bearer_token = AsyncMock(return_value="Bearer super-secret-token")
    client.widgets.ensure_easyiq_session = AsyncMock()
    client.widgets._easyiq_parent_login_id = None
    client.widgets.resolve_easyiq_child_login = Mock(return_value=None)
    client.widgets.resolve_easyiq_child_id = Mock(side_effect=lambda uid: easyiq_ids.get(uid))
    client.widgets.easyiq_identifier_variants = Mock(return_value=[("4242", "astr8360")])
    client.widgets.switch_easyiq_child = AsyncMock()

    def _headers(token, institution_filter, guardian_login, child_user_ids, child_user_id=""):
        return {
            "Authorization": token,
            "Accept": "application/json",
            "x-institutionfilter": ",".join(institution_filter),
            "x-login": guardian_login,
            "x-child": child_user_id,
            "x-childfilter": ",".join(child_user_ids),
        }

    client.widgets.easyiq_headers = Mock(side_effect=_headers)
    client._request_with_version_retry = AsyncMock(side_effect=responses)
    return client


class TestProbeEasyiqChildren:
    @pytest.mark.asyncio
    async def test_summarises_rows_ids_activities_and_item_types(self):
        client = _client(
            [
                _resp(
                    200,
                    [
                        {"Id": "1", "ItemType": 9, "ActivitiesDisplay": "6A"},
                        {"Id": "2", "ItemType": 8, "ActivitiesDisplay": "6A"},
                    ],
                )
            ]
        )
        child = _child("astr8360")

        report = await probe_easyiq_children(
            client, [child], "guardian-1", "2026-W09", ["inst-1"], ["astr8360"]
        )

        entry = report.children[0]
        assert entry.row_count == 2
        assert entry.unique_id_count == 2
        assert entry.activities_display == ["6A"]
        assert entry.item_types == ["8", "9"]
        assert entry.url == CALENDAR_URL
        # loginId is identifier-shaped, so it is symbolised by default rather
        # than the raw "4242" (this child's institution profile id).
        assert entry.params["loginId"] == "child1_profile_id"
        # Authorization is redacted; the bearer token never appears.
        assert entry.headers["Authorization"] == "REDACTED"
        assert "super-secret-token" not in str(entry.headers)

    @pytest.mark.asyncio
    async def test_establishes_the_session_before_reading(self):
        client = _client([_resp(200, [])])

        await probe_easyiq_children(
            client, [_child("astr8360")], "guardian-1", "2026-W09", ["inst-1"], ["astr8360", "k2"]
        )

        client.widgets.ensure_easyiq_session.assert_awaited_once_with(
            ["inst-1"], "guardian-1", ["astr8360", "k2"]
        )

    @pytest.mark.asyncio
    async def test_overlap_matrix_is_zero_for_disjoint_children(self):
        client = _client(
            [
                _resp(200, [{"Id": "1", "ItemType": 9}]),
                _resp(200, [{"Id": "2", "ItemType": 9}]),
            ]
        )

        report = await probe_easyiq_children(
            client,
            [_child("astr8360"), _child("kris37r9")],
            "guardian-1",
            "2026-W09",
            ["inst-1"],
            ["astr8360", "kris37r9"],
        )

        a, b = report.children
        assert len(a.ids & b.ids) == 0

    @pytest.mark.asyncio
    async def test_overlap_matrix_reveals_shared_ids(self):
        """The bug this command exists to catch: two children sharing rows."""
        client = _client(
            [
                _resp(200, [{"Id": "1", "ItemType": 9}]),
                _resp(200, [{"Id": "1", "ItemType": 9}]),
            ]
        )

        report = await probe_easyiq_children(
            client,
            [_child("astr8360"), _child("kris37r9")],
            "guardian-1",
            "2026-W09",
            ["inst-1"],
            ["astr8360", "kris37r9"],
        )

        a, b = report.children
        assert len(a.ids & b.ids) == 1

    @pytest.mark.asyncio
    async def test_switch_child_off_by_default(self):
        client = _client([_resp(200, [])], easyiq_ids={"astr8360": "9001"})

        report = await probe_easyiq_children(
            client, [_child("astr8360")], "guardian-1", "2026-W09", ["inst-1"], ["astr8360"]
        )

        client.widgets.switch_easyiq_child.assert_not_awaited()
        assert report.switch_child_enabled is False
        assert report.children[0].switch_child == ""

    @pytest.mark.asyncio
    async def test_switch_child_posts_before_the_read_when_enabled(self):
        client = _client([_resp(200, [])], easyiq_ids={"astr8360": "9001"})

        report = await probe_easyiq_children(
            client,
            [_child("astr8360")],
            "guardian-1",
            "2026-W09",
            ["inst-1"],
            ["astr8360"],
            switch_child=True,
        )

        client.widgets.switch_easyiq_child.assert_awaited_once_with(
            "9001", ["inst-1"], "guardian-1", ["astr8360"], "astr8360"
        )
        assert report.children[0].switch_child == "ok"

    @pytest.mark.asyncio
    async def test_switch_child_skipped_without_a_resolved_easyiq_id(self):
        client = _client([_resp(200, [])])  # resolve_easyiq_child_id -> None

        report = await probe_easyiq_children(
            client,
            [_child("astr8360")],
            "guardian-1",
            "2026-W09",
            ["inst-1"],
            ["astr8360"],
            switch_child=True,
        )

        client.widgets.switch_easyiq_child.assert_not_awaited()
        assert "skipped" in report.children[0].switch_child

    @pytest.mark.asyncio
    async def test_values_are_only_captured_when_asked_for(self):
        client = _client([_resp(200, [{"Id": "1", "Courses": "Dansk", "Description": "Text"}])])

        report = await probe_easyiq_children(
            client, [_child("astr8360")], "guardian-1", "2026-W09", ["inst-1"], ["astr8360"]
        )
        assert report.children[0].values == []

        client = _client([_resp(200, [{"Id": "1", "Courses": "Dansk", "Description": "Text"}])])
        report = await probe_easyiq_children(
            client,
            [_child("astr8360")],
            "guardian-1",
            "2026-W09",
            ["inst-1"],
            ["astr8360"],
            include_values=True,
        )
        assert report.children[0].values == [{"title": "Dansk", "description": "Text"}]

    @pytest.mark.asyncio
    async def test_default_output_hides_real_login_ids(self):
        """The actual leak this command must not repeat: real identifiers in
        headers/params, not just the bearer token."""
        client = _client([_resp(200, [])])
        client.widgets._easyiq_parent_login_id = "PARENT-REAL-LOGIN-ID"
        client.widgets.resolve_easyiq_child_login = Mock(return_value="CHILD-REAL-UNILOGIN")
        client.widgets.easyiq_identifier_variants = Mock(
            return_value=[("PARENT-REAL-LOGIN-ID", "CHILD-REAL-UNILOGIN")]
        )

        report = await probe_easyiq_children(
            client,
            [_child("CHILD-REAL-UNILOGIN")],
            "GUARDIAN-REAL-LOGIN",
            "2026-W09",
            ["inst-1"],
            ["CHILD-REAL-UNILOGIN"],
        )
        text = "\n".join(render_child_report(report))

        assert "CHILD-REAL-UNILOGIN" not in text
        assert "PARENT-REAL-LOGIN-ID" not in text
        assert "GUARDIAN-REAL-LOGIN" not in text

    @pytest.mark.asyncio
    async def test_different_children_get_different_placeholders(self):
        client = _client([_resp(200, []), _resp(200, [])])
        client.widgets.easyiq_identifier_variants = Mock(
            side_effect=[
                [("4242", "LOGIN-A")],
                [("4242", "LOGIN-B")],
            ]
        )

        report = await probe_easyiq_children(
            client,
            [_child("LOGIN-A"), _child("LOGIN-B")],
            "guardian-1",
            "2026-W09",
            ["inst-1"],
            ["LOGIN-A", "LOGIN-B"],
        )

        c1, c2 = report.children
        assert c1.headers["x-child"] != c2.headers["x-child"]
        assert "LOGIN-A" not in c1.headers["x-child"]
        assert "LOGIN-B" not in c2.headers["x-child"]

    @pytest.mark.asyncio
    async def test_a_value_shared_across_children_gets_the_same_placeholder(self):
        """The bug this command exists to catch, surviving symbolisation: if
        two children's requests are actually built with the same real login,
        that must still be visible as the same placeholder for both."""
        client = _client([_resp(200, []), _resp(200, [])])
        client.widgets.easyiq_identifier_variants = Mock(
            side_effect=[
                [("4242", "LOGIN-A")],
                # Child 2's own login is LOGIN-B, but the (buggy) request was
                # actually built with child 1's login.
                [("4242", "LOGIN-A")],
            ]
        )

        report = await probe_easyiq_children(
            client,
            [_child("LOGIN-A"), _child("LOGIN-B")],
            "guardian-1",
            "2026-W09",
            ["inst-1"],
            ["LOGIN-A", "LOGIN-B"],
        )

        c1, c2 = report.children
        assert c1.headers["x-child"] == c2.headers["x-child"] == "child1_user_id"

    @pytest.mark.asyncio
    async def test_include_values_reveals_real_identifiers(self):
        client = _client([_resp(200, [])])
        client.widgets._easyiq_parent_login_id = "PARENT-REAL-LOGIN-ID"
        client.widgets.easyiq_identifier_variants = Mock(
            return_value=[("PARENT-REAL-LOGIN-ID", "CHILD-REAL-UNILOGIN")]
        )

        report = await probe_easyiq_children(
            client,
            [_child("CHILD-REAL-UNILOGIN")],
            "GUARDIAN-REAL-LOGIN",
            "2026-W09",
            ["inst-1"],
            ["CHILD-REAL-UNILOGIN"],
            include_values=True,
        )

        entry = report.children[0]
        assert entry.params["loginId"] == "PARENT-REAL-LOGIN-ID"
        assert entry.headers["x-child"] == "CHILD-REAL-UNILOGIN"
        assert entry.headers["x-login"] == "GUARDIAN-REAL-LOGIN"
        # Even --include-values never reveals the bearer token.
        assert entry.headers["Authorization"] == "REDACTED"

    @pytest.mark.asyncio
    async def test_a_failing_read_is_recorded_not_raised(self):
        client = _client([Exception("boom")])

        report = await probe_easyiq_children(
            client, [_child("astr8360")], "guardian-1", "2026-W09", ["inst-1"], ["astr8360"]
        )

        assert "boom" in report.children[0].error
        assert report.children[0].url == ""


class TestRenderChildReport:
    def _report(self) -> ChildProbeReport:
        entry = ChildRequestReport(
            label="Child 1 of 2",
            identifier_variant="loginId=parent_login_id child=real_login",
            url=CALENDAR_URL,
            params={"loginId": "parent-42", "date": "2026-02-23T00:00:00Z"},
            headers={"Authorization": "REDACTED", "x-child": "astr8360"},
            status=200,
            row_count=2,
            unique_id_count=2,
            activities_display=["6A"],
            item_types=["9"],
            values=[{"title": "Dansk", "description": "Read pages 1-5"}],
            ids={"1", "2"},
        )
        return ChildProbeReport(switch_child_enabled=False, children=[entry])

    def test_default_output_has_no_token_or_titles(self):
        text = "\n".join(render_child_report(self._report()))

        assert "REDACTED" in text
        assert "Dansk" not in text
        assert "No child names, titles, descriptions or bearer token" in text

    def test_include_values_prints_titles_and_warns(self):
        text = "\n".join(render_child_report(self._report(), include_values=True))

        assert "Dansk" in text
        assert "Read pages 1-5" in text
        assert "Do not paste this publicly" in text

    def test_overlap_matrix_is_printed_for_multiple_children(self):
        report = self._report()
        report.children.append(
            ChildRequestReport(label="Child 2 of 2", url=CALENDAR_URL, ids={"2", "3"})
        )
        text = "\n".join(render_child_report(report))

        assert "Overlap matrix" in text
        assert "C1" in text and "C2" in text

    def test_single_child_has_nothing_to_compare(self):
        text = "\n".join(render_child_report(self._report()))
        assert "nothing to compare" in text

    def test_a_failed_child_is_reported_without_a_request(self):
        report = ChildProbeReport(children=[ChildRequestReport(label="Child 1", error="boom")])
        text = "\n".join(render_child_report(report))
        assert "failed: boom" in text
