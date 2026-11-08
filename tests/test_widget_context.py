"""Tests for aula.widgets.WidgetContext."""

import pytest

from aula.models import Child
from aula.widgets import WidgetContext, easyiq_child_user_ids

PROFILE_CONTEXT = {"data": {"userId": "guardian-login"}}


def _child(child_id: int, user_id: str | None, institution_code: str | None) -> Child:
    return Child(
        id=child_id,
        profile_id=child_id + 1000,
        name=f"Child{child_id}",
        institution_name="School",
        profile_picture="",
        user_id=user_id,
        institution_code=institution_code,
    )


def test_siblings_at_one_school_share_one_institution_filter_entry():
    children = [_child(1, "kid-one", "111111"), _child(2, "kid-two", "111111")]

    ctx = WidgetContext.from_children(children, PROFILE_CONTEXT)

    assert ctx.child_filter == ["kid-one", "kid-two"]
    assert ctx.institution_filter == ["111111"]
    assert ctx.session_uuid == "guardian-login"


def test_scoping_to_one_child_leaves_out_a_sibling_at_another_school():
    family = [_child(1, "kid-one", "111111"), _child(2, "kid-two", "222222")]

    ctx = WidgetContext.from_children(family[1:], PROFILE_CONTEXT)

    assert ctx.child_filter == ["kid-two"]
    assert ctx.institution_filter == ["222222"]


def test_children_without_a_unilogin_cannot_address_a_widget():
    children = [_child(1, None, "111111")]

    with pytest.raises(ValueError, match="UniLogin"):
        WidgetContext.from_children(children, PROFILE_CONTEXT)


@pytest.mark.parametrize("profile_context", [{}, {"data": None}, {"data": {}}])
def test_a_profile_context_without_the_guardian_cannot_open_a_widget_session(profile_context):
    children = [_child(1, "kid-one", "111111")]

    with pytest.raises(ValueError, match="guardian"):
        WidgetContext.from_children(children, profile_context)


def test_easyiq_reads_the_children_at_the_active_institution():
    profile_context = {
        "data": {
            "institutionProfile": {"relations": [{"userId": "kid-one"}, {"userId": "kid-two"}]}
        }
    }

    assert easyiq_child_user_ids(profile_context) == ["kid-one", "kid-two"]


def test_easyiq_includes_a_sibling_at_another_institution_once():
    profile_context = {
        "data": {
            "institutionProfile": {"relations": [{"userId": "kid-one"}]},
            "institutions": [
                {"children": [{"userId": "kid-one"}]},
                {"children": [{"userId": "kid-two"}]},
            ],
        }
    }

    assert easyiq_child_user_ids(profile_context) == ["kid-one", "kid-two"]


def test_easyiq_skips_entries_without_a_unilogin():
    profile_context = {
        "data": {
            "institutionProfile": {"relations": [{"userId": None}, "not-a-child", {"userId": 42}]},
            "institutions": ["not-an-institution", {"children": None}],
        }
    }

    assert easyiq_child_user_ids(profile_context) == ["42"]


@pytest.mark.parametrize("profile_context", [{}, {"data": None}])
def test_easyiq_finds_no_children_in_an_empty_profile_context(profile_context):
    assert easyiq_child_user_ids(profile_context) == []
