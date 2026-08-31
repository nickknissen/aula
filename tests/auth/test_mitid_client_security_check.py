"""Tests for aula.auth.mitid_client step 2 — STIL's bot-defence gate.

Some clients get an F5 bot check spliced into the redirect chain in front of
the UniLogin broker. Passing it needs a JavaScript engine, so all this client
can do is say so clearly instead of reporting an unrecognised page.
"""

import httpx
import pytest

from aula.auth.exceptions import SAMLError, SecurityCheckError
from aula.auth.mitid_client import MitIDAuthClient

BROKER = "https://broker.unilogin.dk"
SECURITY_CHECK = "https://security-check.stil.dk"
MITID = "https://nemlog-in.mitid.dk"
SAML_STIL = f"{BROKER}/auth/realms/broker/protocol/saml-stil?SAMLRequest=fZLd"

# What the gate serves: an F5 challenge page whose cookie is set by script.
CHALLENGE_PAGE = """
<html><head><script>window["bobcmn"] = "10111110101010200";</script></head>
<body><noscript>Please enable JavaScript to view the page content.</noscript></body></html>
"""

MITID_PAGE = """
<html><body><input type="hidden" name="__RequestVerificationToken" value="tok-1"/></body></html>
"""


async def _challenged(request: httpx.Request) -> httpx.Response:
    """The chain observed in issue #43: the broker bounces through NDBD to the gate."""
    if request.url.path.startswith("/auth/realms/broker"):
        return httpx.Response(302, headers={"Location": f"{BROKER}/NDBD/init?data=e3N0"})
    if request.url.host == "broker.unilogin.dk" and request.url.path == "/NDBD/init":
        return httpx.Response(
            302, headers={"Location": f"{SECURITY_CHECK}/NDBD/validate?config=UNILOGIN&data=YLi0"}
        )
    if request.url.host == "security-check.stil.dk":
        return httpx.Response(200, text=CHALLENGE_PAGE)
    return httpx.Response(404)


async def _unchallenged(request: httpx.Request) -> httpx.Response:
    if request.url.path.startswith("/auth/realms/broker"):
        return httpx.Response(302, headers={"Location": f"{MITID}/login/mitid"})
    return httpx.Response(200, text=MITID_PAGE)


def _client(handler) -> MitIDAuthClient:
    transport = httpx.MockTransport(handler)
    return MitIDAuthClient(
        mitid_username="tester",
        httpx_client=httpx.AsyncClient(transport=transport, follow_redirects=False),
    )


class TestStep2SecurityCheck:
    @pytest.mark.asyncio
    async def test_gate_is_reported_as_a_security_check(self):
        client = _client(_challenged)

        with pytest.raises(SecurityCheckError) as excinfo:
            await client._step2_follow_redirect_to_mitid(SAML_STIL)

        message = str(excinfo.value)
        assert "security-check.stil.dk" in message
        assert "Danish IP" in message

    @pytest.mark.asyncio
    async def test_gate_error_is_still_a_saml_error(self):
        """Callers that already handle SAMLError keep working."""
        client = _client(_challenged)

        with pytest.raises(SAMLError):
            await client._step2_follow_redirect_to_mitid(SAML_STIL)

    @pytest.mark.asyncio
    async def test_unchallenged_chain_still_reaches_mitid(self):
        client = _client(_unchallenged)

        result = await client._step2_follow_redirect_to_mitid(SAML_STIL)

        assert result["verification_token"] == "tok-1"
        assert result["mitid_url"] == f"{MITID}/login/mitid"
