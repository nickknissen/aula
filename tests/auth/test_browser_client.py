"""Tests for aula.auth.browser_client — the MitID kodeviser (TOKEN) flow."""

import asyncio
import json
import logging

import httpx
import pytest

from aula.auth.browser_client import BrowserClient
from aula.auth.exceptions import MitIDError, PasswordInvalidError, TokenInvalidError

SESSION_ID = "auth-session-1"
TOKEN_SESSION_ID = "token-session-1"
PASSWORD_SESSION_ID = "password-session-1"
FINALIZATION_SESSION_ID = "final-session-1"
AUTHORIZATION_CODE = "authorization-code-xyz"

CORE = "https://www.mitid.dk/mitid-core-client-backend"
TOKEN_AUTH = "https://www.mitid.dk/mitid-code-token-auth/v1/authenticator-sessions"
PASSWORD_AUTH = "https://www.mitid.dk/mitid-password-auth/v1/authenticator-sessions"


def _authenticator(auth_type: str, session_id: str) -> dict:
    return {
        "authenticatorType": auth_type,
        "authenticatorSessionFlowKey": "flow-key",
        "eafeHash": "eafe-hash",
        "authenticatorSessionId": session_id,
    }


def _srp_init(with_pbkdf2: bool = False) -> dict:
    """SRP values the real backend returns; any well-formed hex works here."""
    payload = {"srpSalt": {"value": "a1b2c3d4"}, "randomB": {"value": "4f5e6d7c8b"}}
    if with_pbkdf2:
        payload["pbkdf2Salt"] = {"value": "0f1e2d3c"}
    return payload


class FakeMitID:
    """Minimal MitID backend covering identify -> kodeviser -> password -> finalize."""

    def __init__(
        self,
        *,
        latency: float = 0.0,
        totp_invalid: bool = False,
        password_invalid: bool = False,
        authenticator_after_token: str = "PASSWORD",
        extra_combinations: list[dict] | None = None,
    ):
        self.latency = latency
        self.totp_invalid = totp_invalid
        self.password_invalid = password_invalid
        self.authenticator_after_token = authenticator_after_token
        self.extra_combinations = extra_combinations or []

        self.paths: list[str] = []
        self.bodies: dict[str, dict] = {}
        self._token_proved = False
        self._password_proved = False

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.latency:
            await asyncio.sleep(self.latency)

        url = str(request.url)
        self.paths.append(f"{request.method} {request.url.path}")

        if request.method == "GET" and url == f"{CORE}/v1/authentication-sessions/{SESSION_ID}":
            return httpx.Response(
                200,
                json={
                    "brokerSecurityContext": "broker-context",
                    "serviceProviderName": "Aula",
                    "referenceTextHeader": "Log ind",
                    "referenceTextBody": "Aula",
                },
            )

        if request.method == "PUT" and url == f"{CORE}/v1/authentication-sessions/{SESSION_ID}":
            return httpx.Response(200, json={})

        if url == f"{CORE}/v2/authentication-sessions/{SESSION_ID}/next":
            return self._handle_next(request)

        if url == f"{TOKEN_AUTH}/{TOKEN_SESSION_ID}/codetoken-init":
            return httpx.Response(200, json=_srp_init())

        if url == f"{TOKEN_AUTH}/{TOKEN_SESSION_ID}/codetoken-prove":
            self.bodies["codetoken-prove"] = _json_body(request)
            self._token_proved = True
            return httpx.Response(204)

        if url == f"{PASSWORD_AUTH}/{PASSWORD_SESSION_ID}/init":
            return httpx.Response(200, json=_srp_init(with_pbkdf2=True))

        if url == f"{PASSWORD_AUTH}/{PASSWORD_SESSION_ID}/password-prove":
            self.bodies["password-prove"] = _json_body(request)
            self._password_proved = True
            return httpx.Response(204)

        if url == f"{CORE}/v1/authentication-sessions/{FINALIZATION_SESSION_ID}/finalization":
            return httpx.Response(200, json={"authorizationCode": AUTHORIZATION_CODE})

        raise AssertionError(f"unexpected request: {request.method} {url}")

    def _handle_next(self, request: httpx.Request) -> httpx.Response:
        combination_id = _json_body(request)["combinationId"]

        # Selecting the kodeviser explicitly.
        if combination_id == "S1":
            return httpx.Response(
                200,
                json={"errors": [], "nextAuthenticator": _authenticator("TOKEN", TOKEN_SESSION_ID)},
            )

        # Advancing after the password proof: hand back the finalization session.
        if self._password_proved:
            if self.password_invalid:
                return httpx.Response(
                    200,
                    json={"errors": [{"errorCode": "PASSWORD_INVALID", "message": "wrong"}]},
                )
            return httpx.Response(
                200, json={"errors": [], "nextSessionId": FINALIZATION_SESSION_ID}
            )

        # Advancing after the kodeviser proof: the backend asks for the password.
        if self._token_proved:
            if self.totp_invalid:
                return httpx.Response(
                    200, json={"errors": [{"errorCode": "TOTP_INVALID", "message": "wrong"}]}
                )
            return httpx.Response(
                200,
                json={
                    "errors": [],
                    "nextAuthenticator": _authenticator(
                        self.authenticator_after_token, PASSWORD_SESSION_ID
                    ),
                },
            )

        # The identify step: MitID defaults to the app authenticator.
        return httpx.Response(
            200,
            json={
                "errors": [],
                "nextAuthenticator": _authenticator("APP", "app-session-1"),
                "combinations": [
                    {"id": "S3", "combinationItems": [{"name": "MitID app"}]},
                    {"id": "S1", "combinationItems": [{"name": "MitID kodeviser"}]},
                    *self.extra_combinations,
                ],
            },
        )


def _json_body(request: httpx.Request) -> dict:
    return json.loads(request.content)


async def _identified_client(server: FakeMitID) -> tuple[BrowserClient, dict[str, str]]:
    """Run initialize + identify, leaving the client ready to authenticate."""
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(server))
    client = BrowserClient("client-hash", SESSION_ID, http_client)
    await client.initialize()
    authenticators = await client.identify_as_user_and_get_available_authenticators("tester")
    return client, authenticators


class TestKodeviserFlow:
    @pytest.mark.asyncio
    async def test_returns_authorization_code(self):
        server = FakeMitID()
        client, _ = await _identified_client(server)

        await client.authenticate_with_token_and_password("123456", "hunter2")
        code = await client.finalize_authentication_and_get_authorization_code()

        assert code == AUTHORIZATION_CODE

    @pytest.mark.asyncio
    async def test_walks_the_two_phase_handshake_in_order(self):
        """Kodeviser proof must precede the password phase; MitID rejects any other order."""
        server = FakeMitID()
        client, _ = await _identified_client(server)

        await client.authenticate_with_token_and_password("123456", "hunter2")
        await client.finalize_authentication_and_get_authorization_code()

        proof_steps = [p for p in server.paths if p.endswith(("prove", "finalization"))]
        assert proof_steps == [
            f"POST /mitid-code-token-auth/v1/authenticator-sessions/{TOKEN_SESSION_ID}"
            "/codetoken-prove",
            f"POST /mitid-password-auth/v1/authenticator-sessions/{PASSWORD_SESSION_ID}"
            "/password-prove",
            f"PUT /mitid-core-client-backend/v1/authentication-sessions"
            f"/{FINALIZATION_SESSION_ID}/finalization",
        ]

    @pytest.mark.asyncio
    async def test_identify_reports_kodeviser_as_available(self):
        server = FakeMitID()
        _, authenticators = await _identified_client(server)

        assert authenticators == {"APP": "MitID app", "TOKEN": "MitID kodeviser"}

    @pytest.mark.asyncio
    async def test_each_proof_carries_m1_and_flow_value_proof(self):
        server = FakeMitID()
        client, _ = await _identified_client(server)

        await client.authenticate_with_token_and_password("123456", "hunter2")

        for step in ("codetoken-prove", "password-prove"):
            body = server.bodies[step]
            assert body["m1"]["value"]
            assert body["flowValueProof"]["value"]

    @pytest.mark.asyncio
    async def test_rejected_token_code_raises_token_invalid(self):
        server = FakeMitID(totp_invalid=True)
        client, _ = await _identified_client(server)

        with pytest.raises(TokenInvalidError):
            await client.authenticate_with_token_and_password("000000", "hunter2")

    @pytest.mark.asyncio
    async def test_rejected_password_raises_password_invalid(self):
        server = FakeMitID(password_invalid=True)
        client, _ = await _identified_client(server)

        with pytest.raises(PasswordInvalidError):
            await client.authenticate_with_token_and_password("123456", "wrong")

    @pytest.mark.asyncio
    async def test_unexpected_authenticator_after_token_is_rejected(self):
        """A backend that asks for something other than the password is not a flow we can drive."""
        server = FakeMitID(authenticator_after_token="CHIP")
        client, _ = await _identified_client(server)

        with pytest.raises(MitIDError, match="Expected PASSWORD"):
            await client.authenticate_with_token_and_password("123456", "hunter2")

    @pytest.mark.asyncio
    async def test_unsupported_combinations_are_logged_not_dropped_silently(self, caplog):
        """Chip and audio readers show up here; users need to know why they're unusable."""
        server = FakeMitID(
            extra_combinations=[{"id": "S9", "combinationItems": [{"name": "MitID chip"}]}]
        )

        with caplog.at_level(logging.WARNING, logger="aula.auth.browser_client"):
            _, authenticators = await _identified_client(server)

        assert "S9" not in authenticators
        assert "S9" in caplog.text


class TestFrontEndProcessingTime:
    """MitID is told how long the client spent on crypto; network time is not that."""

    @pytest.mark.asyncio
    async def test_excludes_network_latency(self):
        latency = 0.2
        server = FakeMitID(latency=latency)
        client, _ = await _identified_client(server)

        await client.authenticate_with_token_and_password("123456", "hunter2")

        # Two round trips (authenticator select + codetoken-init) precede this proof,
        # so a timer spanning them would report at least 2 * latency.
        assert server.bodies["codetoken-prove"]["frontEndProcessingTime"] < latency * 2 * 1000

    @pytest.mark.asyncio
    async def test_still_measures_real_compute(self):
        """PBKDF2 at 20k iterations is the bulk of it; reporting zero would be a lie."""
        server = FakeMitID()
        client, _ = await _identified_client(server)

        await client.authenticate_with_token_and_password("123456", "hunter2")

        assert server.bodies["password-prove"]["frontEndProcessingTime"] > 0
