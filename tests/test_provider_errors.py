"""A widget provider's refusal never touches the Aula session (docs/adr/0001)."""

import logging
from unittest.mock import AsyncMock

import pytest

from aula import AulaAuthenticationError, ProviderAuthenticationError
from aula.api_client import AulaApiClient
from aula.const import (
    EASYIQ_PORTAL,
    EASYIQ_SWITCHCHILD_PATH,
    MIN_UDDANNELSE_API,
    WIDGET_EASYIQ_WEEKPLAN,
    WIDGET_MIN_UDDANNELSE_TASKS,
)
from aula.http import HttpRequestError, HttpResponse
from aula.widgets.client import _EasyIQContext
from tests.fakes import FakeHttpClient

WIDGET_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzZXNzaW9uLTEifQ.c2lnbmF0dXJlLTE"
MU_TASKS_URL = f"{MIN_UDDANNELSE_API}/opgaveliste"
AULA_OK = HttpResponse(200, {"status": {"code": 0}, "data": {}})
TOKEN_OK = HttpResponse(200, {"status": {"code": 0}, "data": WIDGET_TOKEN})


def _client(*mu_answers: HttpResponse, token_answers: tuple[HttpResponse, ...] = (TOKEN_OK,)):
    http = FakeHttpClient()
    refresh = AsyncMock(return_value="new-access-token")
    client = AulaApiClient(http, on_token_refresh=refresh)
    http.route(client.api_url, AULA_OK)
    http.route(f"{client.api_url}?method=aulaToken.getAulaToken", *token_answers)
    http.route(MU_TASKS_URL, *mu_answers)
    return client, http, refresh


async def _read_mu_tasks(client: AulaApiClient):
    return await client.widgets.get_mu_tasks(
        widget_id=WIDGET_MIN_UDDANNELSE_TASKS,
        child_filter=["barn0001"],
        institution_filter=["inst-1"],
        week="2026-W46",
        session_uuid="session-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_a_provider_refusal_is_not_an_aula_authentication_error(status):
    client, http, refresh = _client(HttpResponse(status, None))

    with pytest.raises(ProviderAuthenticationError) as exc_info:
        await _read_mu_tasks(client)

    assert not isinstance(exc_info.value, AulaAuthenticationError)
    assert exc_info.value.status_code == status
    assert exc_info.value.widget_id == WIDGET_MIN_UDDANNELSE_TASKS
    refresh.assert_not_awaited()
    assert len(http.requests_to(MU_TASKS_URL)) == 1


@pytest.mark.asyncio
async def test_a_provider_410_leaves_the_aula_version_alone():
    client, http, _ = _client(HttpResponse(410, None))
    api_url = client.api_url

    with pytest.raises(HttpRequestError):
        await _read_mu_tasks(client)

    assert client.api_url == api_url
    assert len(http.requests_to(MU_TASKS_URL)) == 1


@pytest.mark.asyncio
async def test_a_provider_body_shaped_like_an_aula_envelope_is_left_to_the_provider_parser():
    expired_looking = {"status": {"code": 1, "subCode": 23}, "opgaver": []}
    client, _, refresh = _client(HttpResponse(200, expired_looking))

    assert await _read_mu_tasks(client) == []
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_aula_still_refreshes_when_the_widget_token_request_itself_is_refused():
    client, http, refresh = _client(
        HttpResponse(200, {"opgaver": []}),
        token_answers=(HttpResponse(401, None), TOKEN_OK),
    )

    assert await _read_mu_tasks(client) == []
    refresh.assert_awaited_once()
    assert http.requests_to(MU_TASKS_URL)[0].headers["Authorization"] == f"Bearer {WIDGET_TOKEN}"


@pytest.mark.asyncio
async def test_the_widget_token_stays_out_of_debug_logs(caplog):
    client, _, _ = _client(HttpResponse(200, {"opgaver": []}))

    with caplog.at_level(logging.DEBUG, logger="aula"):
        await _read_mu_tasks(client)

    assert "aulaToken.getAulaToken" in caplog.text
    assert WIDGET_TOKEN not in caplog.text


@pytest.mark.asyncio
async def test_an_easyiq_portal_refusal_names_the_easyiq_widget():
    client, http, refresh = _client()
    http.route(f"{EASYIQ_PORTAL}{EASYIQ_SWITCHCHILD_PATH}", HttpResponse(401, None))
    context = _EasyIQContext(
        token=f"Bearer {WIDGET_TOKEN}",
        institution_filter=("inst-1",),
        guardian_login="guardian-1",
        child_user_ids=("barn0001",),
        widget_id=WIDGET_EASYIQ_WEEKPLAN,
    )

    with pytest.raises(ProviderAuthenticationError) as exc_info:
        await client.widgets.switch_easyiq_child("9001", context)

    assert exc_info.value.widget_id == WIDGET_EASYIQ_WEEKPLAN
    refresh.assert_not_awaited()
