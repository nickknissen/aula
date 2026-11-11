"""Tests for aula.auth.mitid_client step 5 — the UniLogin broker.

After MitID, the broker shows its post-broker-login page. Its form has a hidden
``selected-aktoer`` field that the page's script fills when the user picks a role.
A user with more than one role, such as a parent who also works at a school, is
refused when it is posted empty.
"""

import logging
from urllib.parse import parse_qsl

import httpx
import pytest

from aula.auth.exceptions import SAMLError
from aula.auth.mitid_client import MitIDAuthClient

BROKER = "https://broker.unilogin.dk"
REALM = f"{BROKER}/auth/realms/broker"
POST_BROKER_LOGIN = (
    f"{REALM}/login-actions/post-broker-login?session_code=SC&execution=EX&client_id=CID&tab_id=TID"
)
AFTER_POST_BROKER_LOGIN = f"{REALM}/broker/after-post-broker-login?session_code=SC2"
AULA_ACS = "https://login.aula.dk/simplesaml/module.php/saml/sp/saml2-acs.php/uni-sp"

SAML_DATA = {"relay_state": "relay-123", "saml_response": "saml-abc"}
SAML_FOR_AULA = {
    "final_saml_response": "final-saml",
    "final_relay_state": "final-relay",
    "form_action": AULA_ACS,
}

ROLE_FORM = f"""
<html><body><form id="kc-form" action="{POST_BROKER_LOGIN}" method="post">
  <input type="hidden" name="selected-aktoer" value=""/>
  <button type="button" onclick="vaelg('KONTAKT')">Forælder</button>
  <button type="button" onclick="vaelg('MEDARBEJDER_EKSTERN')">Medarbejder</button>
</form></body></html>
"""

CONFIRMATION_PAGE = """
<html><body><form action="/auth/realms/broker/login-actions/confirm?session_code=SC3" method="post">
  <input type="hidden" name="confirmed" value="true"/>
  <button id="confirmation-button" type="submit">Fortsæt</button>
</form></body></html>
"""

REJECTION_PAGE = """
<html><body><h1 id="kc-page-title">Log ind på unilogin broker</h1>
<div id="kc-error-message"><p class="instruction">Ugyldig anmodning.</p></div>
</body></html>
"""

PRIVATE_ORGANISATION_PAGE = """
<html><body><h1 id="kc-page-title">Log ind på unilogin broker</h1>
<div class="alert alert-error"><span class="kc-feedback-text">Du er tilknyttet en privat
organisation. Du skal vælge "MitID for privat organisation", som findes under "Lokalt login"
i Loginvælgeren.</span></div>
<a href="/auth/realms/broker/login-actions/restart?client_id=CID&amp;tab_id=TID">Tilbage</a>
</body></html>
"""

FINAL_SAML_PAGE = f"""
<html><body><form method="post" action="{AULA_ACS}">
  <input type="hidden" name="SAMLResponse" value="final-saml"/>
  <input type="hidden" name="RelayState" value="final-relay"/>
</form></body></html>
"""


class FakeBroker:
    """The broker after MitID: a post-broker-login page, then the SAML form for Aula.

    ``roles`` is how many roles the user has. With more than one, an empty role is
    refused with 400. ``confirm`` puts the confirmation page in front of the redirect.
    """

    def __init__(self, page: str = ROLE_FORM, *, roles: int = 1, confirm: bool = False):
        self.page = page
        self.roles = roles
        self.confirm = confirm
        self.posted: list[dict[str, str]] = []
        self.confirmed = False

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path == "/auth/realms/broker/broker/nemlogin3/endpoint":
            return httpx.Response(302, headers={"Location": POST_BROKER_LOGIN})

        if path == "/auth/realms/broker/login-actions/post-broker-login":
            if request.method == "GET":
                return httpx.Response(200, text=self.page)
            form = dict(parse_qsl(request.content.decode(), keep_blank_values=True))
            self.posted.append(form)
            if self.roles > 1 and not form.get("selected-aktoer"):
                return httpx.Response(400, text=REJECTION_PAGE)
            if self.confirm:
                return httpx.Response(200, text=CONFIRMATION_PAGE)
            return httpx.Response(302, headers={"Location": AFTER_POST_BROKER_LOGIN})

        if path == "/auth/realms/broker/login-actions/confirm" and request.method == "POST":
            self.confirmed = dict(parse_qsl(request.content.decode())) == {"confirmed": "true"}
            return httpx.Response(302, headers={"Location": AFTER_POST_BROKER_LOGIN})

        if path == "/auth/realms/broker/broker/after-post-broker-login":
            return httpx.Response(200, text=FINAL_SAML_PAGE)

        return httpx.Response(404)


def _client(backend: FakeBroker) -> MitIDAuthClient:
    transport = httpx.MockTransport(backend)
    return MitIDAuthClient(
        mitid_username="tester",
        httpx_client=httpx.AsyncClient(transport=transport, follow_redirects=False),
    )


class TestStep5SamlBrokerFlow:
    @pytest.mark.asyncio
    async def test_user_with_one_role_gets_the_saml_form_for_aula(self):
        client = _client(FakeBroker(roles=1))

        assert await client._step5_saml_broker_flow(SAML_DATA) == SAML_FOR_AULA

    @pytest.mark.asyncio
    async def test_user_with_several_roles_logs_in_as_guardian(self):
        """A parent who also works at a school was refused with 400 (hass-aula setup)."""
        backend = FakeBroker(roles=2)
        client = _client(backend)

        assert await client._step5_saml_broker_flow(SAML_DATA) == SAML_FOR_AULA
        assert backend.posted == [{"selected-aktoer": "KONTAKT"}]

    @pytest.mark.asyncio
    async def test_form_without_a_role_field_is_posted_unchanged(self):
        page = (
            f'<html><body><form action="{POST_BROKER_LOGIN}">'
            '<input type="hidden" name="state" value="s-1"/></form></body></html>'
        )
        backend = FakeBroker(page)
        client = _client(backend)

        assert await client._step5_saml_broker_flow(SAML_DATA) == SAML_FOR_AULA
        assert backend.posted == [{"state": "s-1"}]

    @pytest.mark.asyncio
    async def test_confirmation_page_is_submitted(self):
        backend = FakeBroker(confirm=True)
        client = _client(backend)

        assert await client._step5_saml_broker_flow(SAML_DATA) == SAML_FOR_AULA
        assert backend.confirmed

    @pytest.mark.asyncio
    async def test_refused_post_says_what_the_broker_page_says(self):
        """A bare status code is undiagnosable from a user's log."""

        class RefusesEverything(FakeBroker):
            async def __call__(self, request: httpx.Request) -> httpx.Response:
                if request.method == "POST" and "post-broker-login" in request.url.path:
                    return httpx.Response(400, text=REJECTION_PAGE)
                return await super().__call__(request)

        client = _client(RefusesEverything())

        with pytest.raises(SAMLError) as excinfo:
            await client._step5_saml_broker_flow(SAML_DATA)

        assert "No redirect from post-broker-login (status: 400)" in str(excinfo.value)
        assert "Ugyldig anmodning." in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_identity_linked_to_a_private_organisation_is_reported(self):
        backend = FakeBroker(PRIVATE_ORGANISATION_PAGE)
        client = _client(backend)

        with pytest.raises(SAMLError) as excinfo:
            await client._step5_saml_broker_flow(SAML_DATA)

        assert "private organisation" in str(excinfo.value)
        assert "Du er tilknyttet en privat organisation." in str(excinfo.value)
        assert backend.posted == []

    @pytest.mark.asyncio
    async def test_broker_form_is_logged_by_field_names_only(self, caplog):
        page = (
            f'<html><body><form action="{POST_BROKER_LOGIN}">'
            '<input type="hidden" name="selected-aktoer" value=""/>'
            '<input type="hidden" name="state" value="s3cr3t-state"/></form></body></html>'
        )
        client = _client(FakeBroker(page))
        caplog.set_level(logging.DEBUG, logger="aula.auth.mitid_client")

        await client._step5_saml_broker_flow(SAML_DATA)

        assert "selected-aktoer, state" in caplog.text
        assert "s3cr3t-state" not in caplog.text
        assert "session_code=SC&" not in caplog.text
