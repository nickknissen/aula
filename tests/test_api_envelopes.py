"""Aula rejections must not become successful empty reader results."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aula.api_client import AulaApiClient
from aula.http import (
    AulaInvalidTokenError,
    AulaRejectedError,
    AulaStepUpRequiredError,
    HttpRequestError,
    HttpResponse,
)


def client_with_responses(*responses, refresh=None):
    http = AsyncMock()
    http.request.side_effect = list(responses)
    http.get_cookie = MagicMock(return_value=None)
    return AulaApiClient(http, on_token_refresh=refresh)


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["calendar", "folders"])
@pytest.mark.parametrize("code", [1, 987])
async def test_explicit_rejection_raises_with_method_and_code(reader, code):
    client = client_with_responses(HttpResponse(200, {"status": {"code": code}, "data": []}))
    with pytest.raises(HttpRequestError, match=f"{code}") as exc:
        if reader == "calendar":
            await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1))
        else:
            await client.get_message_folders()
    assert ("calendar." if reader == "calendar" else "messaging.") in str(exc.value)


@pytest.mark.asyncio
async def test_rejection_carries_code_sub_code_and_http_status():
    client = client_with_responses(HttpResponse(403, {"status": {"code": 10, "subCode": 33}}))
    with pytest.raises(AulaRejectedError) as exc:
        await client.get_message_folders()
    err = exc.value
    assert (err.code, err.sub_code, err.status_code) == (10, 33, 403)
    assert err.api_method == "messaging.getFolders"
    assert str(err) == (
        "Aula rejected messaging.getFolders (status code 10, sub-code 33, HTTP 403)"
    )


@pytest.mark.asyncio
async def test_rejection_without_sub_code_leaves_it_out_of_the_message():
    client = client_with_responses(HttpResponse(200, {"status": {"code": 10}}))
    with pytest.raises(AulaRejectedError) as exc:
        await client.get_message_folders()
    assert exc.value.sub_code is None
    assert str(exc.value).endswith("(status code 10, HTTP 200)")


@pytest.mark.asyncio
async def test_sub_code_13_is_not_treated_as_an_expired_session():
    """Sub-code 13 is a secure-documents sharing error, not an expired session."""
    refresh = AsyncMock(return_value="new-token")
    client = client_with_responses(
        HttpResponse(200, {"status": {"code": 1, "subCode": 13}}), refresh=refresh
    )
    with pytest.raises(AulaRejectedError):
        await client.get_message_folders()
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_empty_calendar_is_valid():
    client = client_with_responses(HttpResponse(200, {"status": {"code": 0}, "data": []}))
    assert await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1)) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subcode,error", [(9, AulaInvalidTokenError), (8, AulaStepUpRequiredError)]
)
async def test_known_auth_subcodes_keep_specific_errors(subcode, error):
    client = client_with_responses(HttpResponse(200, {"status": {"code": 1, "subCode": subcode}}))
    with pytest.raises(error):
        await client.get_message_folders()


@pytest.mark.asyncio
async def test_recovered_auth_envelope_returns_successful_reader_result():
    ok = HttpResponse(200, {"status": {"code": 0}, "data": []})
    refresh = AsyncMock(return_value="new-token")
    client = client_with_responses(
        HttpResponse(200, {"status": {"code": 1, "subCode": 9}}), ok, ok, ok, refresh=refresh
    )
    assert await client.get_calendar_events([100], datetime(2026, 3, 1), datetime(2026, 3, 1)) == []
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_vendor_shape_is_not_validated_as_an_aula_envelope():
    response = HttpResponse(200, {"status": {"code": 999}, "data": []})
    client = client_with_responses(response)
    assert (
        await client._request_with_version_retry("get", "https://vendor.example/data") is response
    )
