"""Tests for the names the aula package exports."""

from aula import AulaAuthenticationError, AulaLoginRequiredError, authenticate_and_create_client
from aula.auth_flow import authenticate_and_create_client as auth_flow_entry_point


def test_exports_login_required_error_and_entry_point():
    assert issubclass(AulaLoginRequiredError, AulaAuthenticationError)
    assert authenticate_and_create_client is auth_flow_entry_point
