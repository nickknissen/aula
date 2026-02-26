"""MitID Authentication Client for Aula - handles complete OAuth 2.0 + SAML + MitID flow."""

import base64
import binascii
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx
import qrcode
from bs4 import BeautifulSoup, Tag

from ..const import (
    APP_REDIRECT_URI,
    AUTH_BASE_URL,
    BROKER_URL,
    MITID_BASE_URL,
    OAUTH_AUTHORIZE_PATH,
    OAUTH_CLIENT_ID,
    OAUTH_SCOPE,
    OAUTH_TOKEN_PATH,
    USER_AGENT,
)
from .browser_client import BrowserClient
from .exceptions import (
    MitIDAuthError,
    MitIDError,
    NetworkError,
    OAuthError,
    SAMLError,
)

_LOGGER = logging.getLogger(__name__)


def _extract_form_data(soup: BeautifulSoup) -> tuple[str, dict[str, str]]:
    """Extract the action URL and hidden input values from the first form on a page.

    Raises:
        SAMLError: If no form or action attribute is found.
    """
    form = soup.find("form")
    if not isinstance(form, Tag):
        raise SAMLError("No form found in page")

    action = form.get("action", "")
    if not action:
        raise SAMLError("Form has no action attribute")

    data: dict[str, str] = {}
    for inp in form.find_all("input"):
        if not isinstance(inp, Tag):
            continue
        name = str(inp.get("name", ""))
        if name:
            data[name] = str(inp.get("value", ""))

    return str(action), data


class MitIDAuthClient:
    """Main client for Aula platform authentication with MitID integration.

    Handles the complete OAuth 2.0/OIDC + SAML + MitID authentication flow.
    Designed to work asynchronously with httpx for non-blocking operations.

    Example::

        async with MitIDAuthClient(mitid_username="your_username") as client:
            await client.authenticate()
            # access_token is now available on client
    """

    # Auth constants imported from const.py (validated against Android app v2.14.4)

    def __init__(
        self,
        mitid_username: str,
        timeout: int = 30,
        on_qr_codes: Callable[[qrcode.QRCode, qrcode.QRCode], None] | None = None,
        httpx_client: httpx.AsyncClient | None = None,
    ):
        self._owns_client = httpx_client is None
        self._client = httpx_client or httpx.AsyncClient(follow_redirects=False, timeout=timeout)
        self._mitid_username = mitid_username
        self._timeout = timeout
        self._on_qr_codes = on_qr_codes

        # The real Android app just sends User-Agent: Android — the server
        # doesn't validate browser-style headers (sec-ch-ua, etc.).
        self._client.headers["User-Agent"] = USER_AGENT

        # Session state
        self._code_verifier: str | None = None
        self._code_challenge: str | None = None
        self._state: str | None = None
        self._tokens: dict[str, Any] | None = None
        self._mitid_client: BrowserClient | None = None

    async def __aenter__(self) -> "MitIDAuthClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # -- Public API --

    async def authenticate(self) -> dict[str, Any]:
        """Execute the complete authentication flow.

        Returns:
            Dict containing ``{"success": True, "tokens": ...}``.
        """

        try:
            saml_redirect_url = await self._step1_start_oauth_flow()
            mitid_data = await self._step2_follow_redirect_to_mitid(saml_redirect_url)
            auth_code = await self._step3_mitid_authentication(mitid_data["verification_token"])
            saml_response_data = await self._step4_complete_mitid_flow(
                mitid_data["verification_token"], auth_code
            )
            broker_data = await self._step5_saml_broker_flow(saml_response_data)
            callback_url = await self._step6_complete_aula_login(broker_data)
            tokens = await self._step7_exchange_oauth_code(callback_url)

            return {"success": True, "tokens": tokens}

        except MitIDAuthError:
            raise
        except Exception as e:
            raise MitIDAuthError(f"Authentication failed: {e}") from e

    @property
    def access_token(self) -> str | None:
        """Get the current access token."""
        return self._tokens.get("access_token") if self._tokens else None

    @property
    def refresh_token(self) -> str | None:
        """Get the current refresh token."""
        return self._tokens.get("refresh_token") if self._tokens else None

    @property
    def is_authenticated(self) -> bool:
        """Check if the client has valid tokens."""
        return bool(self._tokens and self._tokens.get("access_token"))

    @property
    def tokens(self) -> dict[str, Any] | None:
        """The raw token dict (available after authenticate)."""
        return self._tokens

    @tokens.setter
    def tokens(self, value: dict[str, Any]) -> None:
        """Set tokens directly (e.g. from a cached token store)."""
        self._tokens = value

    @property
    def cookies(self) -> httpx.Cookies:
        """The HTTP client's cookie jar."""
        return self._client.cookies

    @property
    def mitid_client(self) -> BrowserClient | None:
        """The underlying BrowserClient (available during step 3+)."""
        return self._mitid_client

    async def close(self) -> None:
        """Close the HTTP client if we own it.

        When an external ``httpx_client`` was injected via the constructor,
        the caller retains ownership and is responsible for closing it.
        """
        if self._owns_client:
            await self._client.aclose()

    # -- Auth flow steps (private) --

    async def _step1_start_oauth_flow(self) -> str:
        """Step 1: Start OAuth authorization flow."""
        _LOGGER.info("Step 1/7: Starting OAuth authorization flow")

        try:
            self._code_verifier, self._code_challenge = self._generate_pkce_parameters()
            self._state = self._generate_state()

            auth_params = {
                "response_type": "code",
                "client_id": OAUTH_CLIENT_ID,
                "scope": OAUTH_SCOPE,
                "redirect_uri": APP_REDIRECT_URI,
                "state": self._state,
                "code_challenge": self._code_challenge,
                "code_challenge_method": "S256",
            }

            auth_url = f"{AUTH_BASE_URL}{OAUTH_AUTHORIZE_PATH}"
            full_auth_url = f"{auth_url}?{urlencode(auth_params)}"

            response = await self._client.get(full_auth_url)

            if response.is_redirect:
                redirect_url = response.headers.get("Location")
                _LOGGER.debug("OAuth redirecting to: %s", redirect_url)
                return redirect_url

            if response.is_success:
                soup = BeautifulSoup(response.text, "html.parser")
                saml_form = soup.find("form")
                if isinstance(saml_form, Tag) and saml_form.get("action"):
                    return str(saml_form["action"])
                raise OAuthError("OAuth authorization returned 200 but no redirect found")

            raise OAuthError(f"Unexpected OAuth response: {response.status_code}")

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during OAuth flow: {e}") from e

    async def _step2_follow_redirect_to_mitid(self, start_url: str) -> dict[str, str]:
        """Step 2: Follow the redirect chain to MitID."""
        _LOGGER.info("Step 2/7: Following redirect chain to MitID")

        current_url = start_url
        max_redirects = 15

        try:
            for redirect_count in range(1, max_redirects + 1):
                response = await self._client.get(current_url)
                _LOGGER.debug(
                    "Redirect %d: HTTP %d → %s",
                    redirect_count,
                    response.status_code,
                    response.url,
                )

                if response.is_success:
                    soup = BeautifulSoup(response.text, "html.parser")

                    if BROKER_URL in str(response.url):
                        _LOGGER.debug("Reached UniLogin broker")
                        return await self._handle_broker_page(soup)

                    if "mitid.dk" in str(response.url) or "nemlog-in" in str(response.url):
                        _LOGGER.debug("Reached MitID page")
                        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
                        if not isinstance(token_input, Tag):
                            raise SAMLError("Could not find RequestVerificationToken on MitID page")

                        return {
                            "verification_token": str(token_input["value"]),
                            "mitid_url": str(response.url),
                        }

                    raise SAMLError(f"Unexpected page reached: {response.url}")

                if response.is_redirect:
                    if "Location" not in response.headers:
                        raise SAMLError("Redirect response missing Location header")
                    current_url = urljoin(str(current_url), response.headers["Location"])
                else:
                    raise SAMLError(f"Unexpected status code: {response.status_code}")

            raise SAMLError(f"Too many redirects ({max_redirects})")

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during redirect chain: {e}") from e

    async def _handle_broker_page(self, soup: BeautifulSoup) -> dict[str, str]:
        """Handle the broker page for MitID selection."""
        action, form_data = _extract_form_data(soup)

        _LOGGER.debug("Submitting MitID selection form to %s", action)
        form_data["selectedIdp"] = "nemlogin3"

        post_response = await self._client.post(action, data=form_data)

        if post_response.is_redirect and "Location" in post_response.headers:
            current_url = post_response.headers["Location"]
            _LOGGER.debug("IdP selection redirected to: %s", current_url)
            return await self._step2_follow_redirect_to_mitid(current_url)

        raise SAMLError("Could not find working IdP selection method")

    async def _step3_mitid_authentication(self, verification_token: str) -> str:
        """Step 3: Perform MitID authentication with the app."""
        _LOGGER.info("Step 3/7: Authenticating with MitID app")

        post_url = f"{MITID_BASE_URL}/login/mitid/initialize"
        post_headers = {
            "accept": "*/*",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "origin": MITID_BASE_URL,
            "referer": f"{MITID_BASE_URL}/login/mitid",
            "x-requested-with": "XMLHttpRequest",
        }

        resp_init = await self._client.post(
            post_url,
            headers=post_headers,
            data={"__RequestVerificationToken": verification_token},
        )
        resp_init_json = resp_init.json()

        if isinstance(resp_init_json, str):
            resp_init_json = json.loads(resp_init_json)

        aux_value = resp_init_json.get("Aux")
        if not aux_value:
            raise MitIDError("No Aux value in MitID initialization response")

        aux = json.loads(base64.b64decode(aux_value).decode())

        client_hash = binascii.hexlify(base64.b64decode(aux["coreClient"]["checksum"])).decode(
            "ascii"
        )
        authentication_session_id = aux["parameters"]["authenticationSessionId"]

        self._mitid_client = BrowserClient(
            client_hash, authentication_session_id, self._client, self._on_qr_codes
        )

        await self._mitid_client.initialize()

        available_authenticators = (
            await self._mitid_client.identify_as_user_and_get_available_authenticators(
                self._mitid_username
            )
        )

        _LOGGER.debug("Available authenticators: %s", available_authenticators)

        if "APP" not in available_authenticators:
            raise MitIDError("APP authentication method not available for this user")

        await self._mitid_client.authenticate_with_app()

        authorization_code = (
            await self._mitid_client.finalize_authentication_and_get_authorization_code()
        )
        _LOGGER.debug("MitID authorization code obtained")
        return authorization_code

    async def _step4_complete_mitid_flow(
        self, verification_token: str, authorization_code: str
    ) -> dict[str, str]:
        """Step 4: Complete MitID authentication and get SAML response."""
        _LOGGER.info("Step 4/7: Completing MitID flow")

        try:
            session_uuid = self._client.cookies.get("SessionUuid", "")
            challenge = self._client.cookies.get("Challenge", "")

            params = {
                "__RequestVerificationToken": verification_token,
                "NewCulture": "",
                "MitIDUseConfirmed": "True",
                "MitIDAuthCode": authorization_code,
                "MitIDAuthenticationCancelled": "",
                "MitIDCoreClientError": "",
                "SessionStorageActiveSessionUuid": session_uuid,
                "SessionStorageActiveChallenge": challenge,
            }

            request = await self._client.post(f"{MITID_BASE_URL}/login/mitid", data=params)

            soup = BeautifulSoup(request.text, features="html.parser")

            relay_state_input = soup.find("input", {"name": "RelayState"})
            saml_response_input = soup.find("input", {"name": "SAMLResponse"})

            if not isinstance(relay_state_input, Tag) or not isinstance(saml_response_input, Tag):
                raise SAMLError("Could not find SAML data in MitID completion response")

            return {
                "relay_state": str(relay_state_input.get("value", "")),
                "saml_response": str(saml_response_input.get("value", "")),
            }

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during MitID completion: {e}") from e

    async def _step5_saml_broker_flow(self, saml_data: dict[str, str]) -> dict[str, str]:
        """Step 5: Complete SAML broker authentication."""
        _LOGGER.info("Step 5/7: Processing SAML broker flow")

        try:
            params = {
                "RelayState": saml_data["relay_state"],
                "SAMLResponse": saml_data["saml_response"],
            }

            broker_response = await self._client.post(
                f"{BROKER_URL}/auth/realms/broker/broker/nemlogin3/endpoint",
                data=params,
            )

            if not broker_response.is_redirect:
                raise SAMLError("No redirect from broker endpoint")

            action_url = broker_response.headers["Location"]
            final_request = await self._client.get(action_url)

            return await self._process_broker_response(final_request)

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during SAML broker flow: {e}") from e

    async def _process_broker_response(self, response: httpx.Response) -> dict[str, str]:
        """Process broker response and extract SAML for Aula."""
        _LOGGER.debug("Processing broker response from URL: %s", response.url)

        soup = BeautifulSoup(response.text, "html.parser")
        action, form_data = _extract_form_data(soup)

        post_broker_response = await self._client.post(action, data=form_data)

        if not post_broker_response.is_redirect:
            raise SAMLError(
                f"No redirect from post-broker-login (status: {post_broker_response.status_code})"
            )

        after_url = post_broker_response.headers["Location"]
        after_response = await self._client.get(after_url)

        after_soup = BeautifulSoup(after_response.text, "html.parser")
        saml_form = after_soup.find("form")

        if not isinstance(saml_form, Tag):
            raise SAMLError("No SAML form found in broker response")

        saml_response_input = saml_form.find("input", {"name": "SAMLResponse"})
        relay_state_input = saml_form.find("input", {"name": "RelayState"})

        if not isinstance(saml_response_input, Tag):
            raise SAMLError("Could not find SAMLResponse")

        return {
            "final_saml_response": str(saml_response_input.get("value", "")),
            "final_relay_state": (
                str(relay_state_input.get("value", ""))
                if isinstance(relay_state_input, Tag)
                else ""
            ),
            "form_action": str(saml_form.get("action", "")),
        }

    async def _step6_complete_aula_login(self, saml_data: dict[str, str]) -> str:
        """Step 6: Complete Aula login with SAML response."""
        _LOGGER.info("Step 6/7: Completing Aula login")

        try:
            aula_saml_data = {
                "SAMLResponse": saml_data["final_saml_response"],
                "RelayState": saml_data["final_relay_state"],
            }

            saml_endpoint = saml_data.get(
                "form_action",
                f"{AUTH_BASE_URL}/simplesaml/module.php/saml/sp/saml2-acs.php/uni-sp",
            )

            aula_response = await self._client.post(saml_endpoint, data=aula_saml_data)

            if not aula_response.is_redirect:
                raise OAuthError("No redirect from Aula SAML endpoint")

            return await self._follow_oauth_callback_redirects(aula_response.headers["Location"])

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during Aula login completion: {e}") from e

    async def _follow_oauth_callback_redirects(self, start_url: str) -> str:
        """Follow redirects to find the OAuth callback URL."""
        redirect_url = start_url
        max_redirects = 10

        for _ in range(max_redirects):
            redirect_response = await self._client.get(redirect_url)

            # Check if this is the OAuth callback
            response_url = str(redirect_response.url)
            if APP_REDIRECT_URI in response_url and "code=" in response_url:
                _LOGGER.debug("Found OAuth callback URL")
                return response_url

            if "Location" in redirect_response.headers:
                location = redirect_response.headers["Location"]
                if APP_REDIRECT_URI in location and "code=" in location:
                    return location
                redirect_url = urljoin(response_url, location)
            elif redirect_response.is_success:
                if APP_REDIRECT_URI in response_url and "code=" in response_url:
                    return response_url
                raise OAuthError(f"Did not receive OAuth callback URL. Final: {response_url}")
            else:
                raise OAuthError(f"Unexpected status: {redirect_response.status_code}")

        raise OAuthError("Too many redirects without finding OAuth callback")

    async def _step7_exchange_oauth_code(self, callback_url: str) -> dict[str, Any]:
        """Step 7: Exchange OAuth authorization code for tokens."""
        _LOGGER.info("Step 7/7: Exchanging authorization code for tokens")

        try:
            parsed_url = urlparse(callback_url)
            query_params = parse_qs(parsed_url.query)

            if "code" not in query_params:
                raise OAuthError("No authorization code in callback URL")

            auth_code = query_params["code"][0]

            if "state" in query_params:
                returned_state = query_params["state"][0]
                if returned_state != self._state:
                    raise OAuthError("State parameter mismatch")

            token_url = f"{AUTH_BASE_URL}{OAUTH_TOKEN_PATH}"

            token_data = {
                "grant_type": "authorization_code",
                "code": auth_code,
                "client_id": OAUTH_CLIENT_ID,
                "redirect_uri": APP_REDIRECT_URI,
                "code_verifier": self._code_verifier,
            }

            response = await self._client.post(
                token_url,
                data=token_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )

            if not response.is_success:
                raise OAuthError(f"Token exchange failed: {response.status_code}")

            tokens = response.json()

            if "expires_in" in tokens:
                tokens["expires_at"] = time.time() + tokens["expires_in"]

            self._tokens = tokens

            if expires_in := tokens.get("expires_in", 0):
                hours, remainder = divmod(int(expires_in), 3600)
                minutes = remainder // 60
                _LOGGER.info("Authentication complete, token lifetime: %dh %dm", hours, minutes)

            return tokens

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during token exchange: {e}") from e
        except json.JSONDecodeError as e:
            raise OAuthError(f"Invalid token response format: {e}") from e

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token using a stored refresh token.

        Args:
            refresh_token: The refresh token from a previous authentication.

        Returns:
            Updated token dict with new access_token and potentially rotated refresh_token.

        Raises:
            OAuthError: If the refresh request fails (expired/revoked token, server error).
        """
        _LOGGER.info("Refreshing access token")

        token_url = f"{AUTH_BASE_URL}{OAUTH_TOKEN_PATH}"

        try:
            response = await self._client.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": OAUTH_CLIENT_ID,
                    "refresh_token": refresh_token,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )

            if not response.is_success:
                raise OAuthError(f"Token refresh failed: {response.status_code}")

            tokens = response.json()

            if "expires_in" in tokens:
                tokens["expires_at"] = time.time() + tokens["expires_in"]

            self._tokens = tokens
            _LOGGER.info("Token refreshed successfully")
            return tokens

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during token refresh: {e}") from e
        except json.JSONDecodeError as e:
            raise OAuthError(f"Invalid token refresh response format: {e}") from e

    # -- Static helpers --

    @staticmethod
    def _generate_pkce_parameters() -> tuple[str, str]:
        """Generate PKCE parameters for OAuth 2.0."""
        code_verifier = (
            base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
        )
        challenge = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = base64.urlsafe_b64encode(challenge).decode("utf-8").rstrip("=")
        return code_verifier, code_challenge

    @staticmethod
    def _generate_state() -> str:
        """Generate OAuth state parameter."""
        return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("utf-8").rstrip("=")
