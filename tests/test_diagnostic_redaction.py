"""Synthetic credentials stay out of application diagnostic records."""

import copy
import logging
from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from aula.api_client import AulaApiClient
from aula.auth.exceptions import SAMLError
from aula.auth.mitid_client import MitIDAuthClient
from aula.auth_flow import authenticate
from aula.http import AulaSessionExpiredError, HttpResponse


@pytest.mark.asyncio
async def test_nested_api_credentials_are_redacted_without_mutating_response(caplog):
    payload = {
        "data": [],
        "Access_Token": "access-marker",
        "refresh_token": "refresh-marker",
        "nested": [
            {
                "CoOkIe": "cookie-marker",
                "Authorization": "bearer-marker",
                "redirect": "https://example.test/callback?code=oauth-marker",
            }
        ],
    }
    original = copy.deepcopy(payload)
    http = AsyncMock()
    http.request.return_value = HttpResponse(200, payload)
    client = AulaApiClient(http)
    with caplog.at_level(logging.DEBUG, logger="aula"):
        assert (
            await client.get_calendar_events([1], datetime(2026, 3, 1), datetime(2026, 3, 1)) == []
        )
    for marker in (
        "access-marker",
        "refresh-marker",
        "cookie-marker",
        "bearer-marker",
        "oauth-marker",
    ):
        assert marker not in caplog.text
    assert "calendar.getEvents" in caplog.text
    assert "200" in caplog.text
    assert payload == original


@pytest.mark.asyncio
async def test_oauth_redirect_log_redacts_query_values_but_preserves_actual_redirect(caplog):
    redirect = "https://example.test/authorize?code=oauth-marker&state=state-marker"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"Location": redirect})
        )
    ) as http:
        client = MitIDAuthClient("tester", httpx_client=http)
        with caplog.at_level(logging.DEBUG, logger="aula"):
            result = await client._step1_start_oauth_flow()
        assert result == redirect
        assert "oauth-marker" not in caplog.text
        assert "state-marker" not in caplog.text
        assert "example.test/authorize" in caplog.text


@pytest.mark.asyncio
async def test_failed_completion_does_not_log_hidden_authentication_html(caplog):
    html = '<form><input type="hidden" name="SAMLResponse" value="saml-marker"></form>'
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    ) as http:
        client = MitIDAuthClient("tester", httpx_client=http)
        with caplog.at_level(logging.DEBUG, logger="aula"), pytest.raises(SAMLError):
            await client._step4_complete_mitid_flow("verify-marker", "code-marker")
    for marker in ("saml-marker", "verify-marker", "code-marker"):
        assert marker not in caplog.text
    assert "HTTP 200" in caplog.text
    assert "SAML" in caplog.text


@pytest.mark.asyncio
async def test_post_reader_diagnostics_sanitize_nested_credentials(caplog):
    payload = {
        "data": {
            "posts": [
                {
                    "id": 1,
                    "title": "Example",
                    "Authorization": "post-marker",
                    "nested": [{"Set-Cookie": "nested-marker"}],
                }
            ]
        }
    }
    original = copy.deepcopy(payload)
    http = AsyncMock()
    http.request.return_value = HttpResponse(200, payload)
    with caplog.at_level(logging.DEBUG, logger="aula"):
        await AulaApiClient(http).get_posts([1])
    assert "post-marker" not in caplog.text
    assert "nested-marker" not in caplog.text
    assert "Processing post" in caplog.text
    assert payload == original


@pytest.mark.asyncio
async def test_authentication_failure_logs_do_not_repeat_url_credentials(caplog):
    redirect = "https://example.test/unexpected?code=failure-marker"

    def endpoint(request):
        if request.url.host == "example.test":
            return httpx.Response(200, text="Unexpected page")
        return httpx.Response(302, headers={"Location": redirect})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        with caplog.at_level(logging.DEBUG, logger="aula"), pytest.raises(RuntimeError):
            await authenticate("tester", httpx_client=http)
    assert "failure-marker" not in caplog.text
    assert "Authentication failed" in caplog.text


@pytest.mark.asyncio
async def test_model_parsing_warnings_redact_credentials_at_reader_entry_point(caplog):
    payload = {"data": [{"location": [{"Authorization": "model-marker"}]}]}
    original = copy.deepcopy(payload)
    http = AsyncMock()
    http.request.return_value = HttpResponse(200, payload)
    with caplog.at_level(logging.DEBUG, logger="aula"):
        await AulaApiClient(http).get_daily_overview(1)
    assert "model-marker" not in caplog.text
    assert "Unexpected location" in caplog.text
    assert payload == original


def test_integer_status_code_is_kept_but_string_code_is_redacted():
    from aula.utils.diagnostics import redact_credentials

    envelope = {"status": {"code": 10, "subCode": 23}}
    assert redact_credentials(envelope) == envelope
    assert redact_credentials({"code": "abc"}) == {"code": "[redacted]"}
    assert redact_credentials({"code": True}) == {"code": "[redacted]"}
    assert redact_credentials({"token": 12345}) == {"token": "[redacted]"}


@pytest.mark.asyncio
async def test_response_log_shows_aula_status_code(caplog):
    payload = {"status": {"code": 10, "subCode": 23}, "data": []}
    http = AsyncMock()
    http.request.return_value = HttpResponse(200, payload)
    client = AulaApiClient(http)
    with caplog.at_level(logging.DEBUG, logger="aula"), pytest.raises(AulaSessionExpiredError):
        await client.get_calendar_events([1], datetime(2026, 3, 1), datetime(2026, 3, 1))
    assert '"code":10' in caplog.text
    assert '"subCode":23' in caplog.text
