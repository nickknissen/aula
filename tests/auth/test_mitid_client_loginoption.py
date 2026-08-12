"""Tests for aula.auth.mitid_client step 4 — the identity selection detour.

A user with a single MitID identity gets the SAML form straight back from
POST /login/mitid. A user with more than one is redirected to /loginoption
first, and has to pick one before the SAML form is produced.
"""

import httpx
import pytest

from aula.auth.exceptions import SAMLError
from aula.auth.mitid_client import MitIDAuthClient

MITID = "https://nemlog-in.mitid.dk"

SAML_FORM = """
<html><body><form>
  <input type="hidden" name="RelayState" value="relay-123"/>
  <input type="hidden" name="SAMLResponse" value="saml-abc"/>
</form></body></html>
"""

LOGIN_OPTION_PAGE = """
<html><body>
  <input type="hidden" name="__RequestVerificationToken" value="tok-1"/>
  <a class="list-link" data-loginoptions='{"id":"priv"}'>
    <div class="list-link-text">Asser Smidt</div>
    <div class="link-list-detail">Privat</div>
  </a>
  <a class="list-link" data-loginoptions='{"id":"biz"}'>
    <div class="list-link-text">Asser Smidt</div>
    <div class="link-list-detail">Firma ApS</div>
  </a>
</body></html>
"""


class FakeNemLogIn:
    """POST /login/mitid answers per `identities`; /loginoption returns the SAML form."""

    def __init__(self, identities: int = 1):
        self.identities = identities
        self.paths: list[str] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(f"{request.method} {request.url.path}")

        if request.url.path == "/login/mitid":
            if self.identities > 1:
                # What the real backend does: bounce to the identity picker.
                return httpx.Response(302, headers={"Location": f"{MITID}/loginoption"})
            return httpx.Response(200, text=SAML_FORM)

        if request.url.path == "/loginoption":
            if request.method == "GET":
                return httpx.Response(200, text=LOGIN_OPTION_PAGE)
            return httpx.Response(200, text=SAML_FORM)

        return httpx.Response(404)


def _client(backend: FakeNemLogIn, **kwargs) -> MitIDAuthClient:
    transport = httpx.MockTransport(backend)
    return MitIDAuthClient(
        mitid_username="tester",
        httpx_client=httpx.AsyncClient(transport=transport, follow_redirects=False),
        **kwargs,
    )


class TestStep4CompleteMitIDFlow:
    @pytest.mark.asyncio
    async def test_single_identity_returns_saml_data(self):
        client = _client(FakeNemLogIn(identities=1))

        result = await client._step4_complete_mitid_flow("verify-token", "auth-code")

        assert result == {"relay_state": "relay-123", "saml_response": "saml-abc"}

    @pytest.mark.asyncio
    async def test_multiple_identities_follows_redirect_to_loginoption(self):
        """The 302 to /loginoption has an empty body — not following it loses the SAML form."""

        async def pick_first(identities: list[str]) -> int:
            assert identities == ["Asser Smidt (Privat)", "Asser Smidt (Firma ApS)"]
            return 0

        backend = FakeNemLogIn(identities=2)
        client = _client(backend, on_identity_selected=pick_first)

        result = await client._step4_complete_mitid_flow("verify-token", "auth-code")

        assert result == {"relay_state": "relay-123", "saml_response": "saml-abc"}
        assert "GET /loginoption" in backend.paths

    @pytest.mark.asyncio
    async def test_reports_missing_saml_data(self):
        class NoSaml(FakeNemLogIn):
            async def __call__(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, text="<html><body>nothing here</body></html>")

        client = _client(NoSaml())

        with pytest.raises(SAMLError, match="Could not find SAML data"):
            await client._step4_complete_mitid_flow("verify-token", "auth-code")
