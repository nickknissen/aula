"""What a caller's callback raises reaches the caller as it is, not as a MitID failure."""

import base64
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from aula.auth.exceptions import MitIDAuthError
from aula.auth.mitid_client import MitIDAuthClient
from tests.auth.test_mitid_client_loginoption import FakeNemLogIn, _client


class PickerClosed(Exception):
    pass


class ScreenGone(Exception):
    pass


@pytest.fixture
def at_mitid():
    """Skip the OAuth start and the SAML redirect, which have their own tests."""
    with (
        patch.object(MitIDAuthClient, "_step1_start_oauth_flow", AsyncMock(return_value="url")),
        patch.object(
            MitIDAuthClient,
            "_step2_follow_redirect_to_mitid",
            AsyncMock(return_value={"verification_token": "verify-token"}),
        ),
    ):
        yield


@pytest.fixture
def past_mitid(at_mitid):
    """Also skip the MitID login itself."""
    step3 = AsyncMock(return_value="auth-code")
    with patch.object(MitIDAuthClient, "_step3_mitid_authentication", step3):
        yield


class MitIDInitialize(FakeNemLogIn):
    """Answers the MitID initialize call that starts step 3."""

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/mitid/initialize":
            aux = {
                "coreClient": {"checksum": base64.b64encode(b"hash").decode()},
                "parameters": {"authenticationSessionId": "session-1"},
            }
            return httpx.Response(
                200, json={"Aux": base64.b64encode(json.dumps(aux).encode()).decode()}
            )
        return await super().__call__(request)


class AppShowingACode:
    """Stands in for the MitID protocol client when the app asks for a code."""

    def __init__(self, *_args, on_otp_code, **_kwargs):
        self._on_otp_code = on_otp_code

    async def initialize(self) -> None:
        pass

    async def identify_as_user_and_get_available_authenticators(self, _username):
        return {"APP": "MitID app"}

    async def authenticate_with_app(self) -> None:
        self._on_otp_code("A1B2")


class TestCallbackErrors:
    @pytest.mark.asyncio
    async def test_identity_callback_error_reaches_the_caller(self, past_mitid):
        async def close_picker(identities: list[str]) -> int:
            raise PickerClosed

        client = _client(FakeNemLogIn(identities=2), on_identity_selected=close_picker)

        with pytest.raises(PickerClosed):
            await client.authenticate()

    @pytest.mark.asyncio
    async def test_display_callback_error_reaches_the_caller(self, at_mitid):
        def show_code(code: str) -> None:
            raise ScreenGone

        client = _client(MitIDInitialize(), on_otp_code=show_code)

        with (
            patch("aula.auth.mitid_client.BrowserClient", AppShowingACode),
            pytest.raises(ScreenGone),
        ):
            await client.authenticate()

    @pytest.mark.asyncio
    async def test_other_failures_are_still_mitid_errors(self):
        failing_start = AsyncMock(side_effect=ValueError("unreadable page"))

        with (
            patch.object(MitIDAuthClient, "_step1_start_oauth_flow", failing_start),
            pytest.raises(MitIDAuthError),
        ):
            await _client(FakeNemLogIn()).authenticate()
