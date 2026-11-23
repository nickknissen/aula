"""A caller's httpx client is used for login but not changed by it."""

import httpx
import pytest

from aula.auth.mitid_client import MitIDAuthClient
from aula.const import USER_AGENT


def _auth(handler=None) -> tuple[MitIDAuthClient, httpx.AsyncClient]:
    transport = httpx.MockTransport(handler or (lambda request: httpx.Response(200)))
    shared = httpx.AsyncClient(transport=transport, headers={"User-Agent": "shared/1.0"})
    return MitIDAuthClient(mitid_username="tester", httpx_client=shared), shared


def test_construction_leaves_client_headers_unchanged():
    _, shared = _auth()

    assert shared.headers["User-Agent"] == "shared/1.0"


@pytest.mark.asyncio
async def test_requests_send_aula_user_agent_and_leave_client_headers():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200)

    auth, shared = _auth(handler)
    await auth._get("https://login.aula.dk/a")
    await auth._post("https://login.aula.dk/b", data={"x": "1"}, headers={"X-Test": "1"})

    assert seen == [USER_AGENT, USER_AGENT]
    assert shared.headers["User-Agent"] == "shared/1.0"


def test_cookies_keep_only_aula_domains():
    auth, shared = _auth()
    shared.cookies.set("PHPSESSID", "a", domain="www.aula.dk")
    shared.cookies.set("Csrfp-Token", "b", domain=".aula.dk")
    shared.cookies.set("Apex", "c", domain="aula.dk")
    shared.cookies.set("SessionUuid", "d", domain="mitid.dk")
    shared.cookies.set("Other", "e", domain="notaula.dk")

    assert auth.cookies == {"PHPSESSID": "a", "Csrfp-Token": "b", "Apex": "c"}
