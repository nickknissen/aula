import logging

import pytest

from aula import ProviderAuthenticationError
from aula.http import AulaNotFoundError, AulaServerError, HttpResponse
from aula.widgets._transport import ProviderTransport
from tests.fakes import FakeHttpClient

PROVIDER_URL = "https://provider.example/api/plan"
WIDGET_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzZXNzaW9uLTEifQ.c2lnbmF0dXJlLTE"


def _transport(*answers: HttpResponse) -> tuple[ProviderTransport, FakeHttpClient]:
    http = FakeHttpClient()
    http.route(PROVIDER_URL, *answers)
    return ProviderTransport(http), http


@pytest.mark.asyncio
async def test_send_passes_the_request_through_and_returns_the_body():
    transport, http = _transport(HttpResponse(200, {"plans": []}))

    body = await transport.send(
        "0030",
        "post",
        PROVIDER_URL,
        headers={"Authorization": "Bearer t"},
        params={"week": "2026-W46"},
        json={"child": "barn0001"},
    )

    assert body == {"plans": []}
    [request] = http.requests
    assert (request.method, request.url) == ("post", PROVIDER_URL)
    assert request.headers == {"Authorization": "Bearer t"}
    assert request.params == {"week": "2026-W46"}
    assert request.json == {"child": "barn0001"}


@pytest.mark.asyncio
async def test_a_body_that_is_not_json_comes_back_as_none():
    transport, _ = _transport(HttpResponse(200, None))

    assert await transport.send("0030", "get", PROVIDER_URL) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_a_refusal_raises_provider_authentication_error_once(status):
    transport, http = _transport(HttpResponse(status, None), HttpResponse(200, {}))

    with pytest.raises(ProviderAuthenticationError) as exc_info:
        await transport.send("0030", "get", PROVIDER_URL)

    assert exc_info.value.status_code == status
    assert exc_info.value.widget_id == "0030"
    assert len(http.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "error"), [(404, AulaNotFoundError), (503, AulaServerError)])
async def test_other_failures_keep_their_usual_error_and_are_not_retried(status, error):
    transport, http = _transport(HttpResponse(status, None), HttpResponse(200, {}))

    with pytest.raises(error):
        await transport.send("0030", "get", PROVIDER_URL)

    assert len(http.requests) == 1


@pytest.mark.asyncio
async def test_the_debug_log_names_the_call_and_redacts_the_body(caplog):
    transport, _ = _transport(HttpResponse(200, {"token": WIDGET_TOKEN, "week": "2026-W46"}))

    with caplog.at_level(logging.DEBUG, logger="aula.widgets._transport"):
        await transport.send(
            "0030",
            "post",
            f"{PROVIDER_URL}?sessionUUID=session-1",
            headers={"Authorization": f"Bearer {WIDGET_TOKEN}"},
            json={"password": "hunter2"},
        )

    text = caplog.text
    assert f"POST {PROVIDER_URL} widget=0030 -> 200" in text
    assert "2026-W46" in text
    assert WIDGET_TOKEN not in text
    assert "session-1" not in text
    assert "hunter2" not in text
