"""Tests for aula.widgets.WidgetContext."""

import pytest

from aula.models import Child
from aula.widgets import WidgetContext

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
