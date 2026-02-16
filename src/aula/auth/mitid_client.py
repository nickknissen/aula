"""MitID Authentication Client for Aula - handles complete OAuth 2.0 + SAML + MitID flow."""

import base64
import binascii
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .browser_client import BrowserClient
from .exceptions import (
    AulaAuthenticationError,
    MitIDError,
    NetworkError,
    OAuthError,
    SAMLError,
)

_LOGGER = logging.getLogger(__name__)


class MitIDAuthClient:
    """
    Main client for Aula platform authentication with MitID integration.

    This class handles the complete OAuth 2.0/OIDC + SAML + MitID authentication flow.
    Designed to work asynchronously with httpx for non-blocking operations.

    Example:
        client = MitIDAuthClient(mitid_username="your_username")
        await client.authenticate()
        access_token = client.access_token
    """

    def __init__(
        self,
        mitid_username: str,
        timeout: int = 30,
        debug: bool = False,
    ):
        """
        Initialize the MitID authentication client.

        Args:
            mitid_username: Your MitID username
            timeout: Request timeout in seconds (default: 30)
            debug: Enable debug logging (default: False)
        """
        self.client = httpx.AsyncClient(follow_redirects=False, timeout=timeout)
        self.mitid_username = mitid_username
        self.timeout = timeout
        self.debug = debug

        # Mobile app user agent
        self.client.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Linux; Android 14; sdk_gphone64_x86_64) "  # noqa: E501
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Mobile Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"  # noqa: E501
                "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Upgrade-Insecure-Requests": "1",
                "sec-ch-ua": '"Google Chrome";v="113", "Chromium";v="113", "Not-A.Brand";v="24"',
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": '"Android"',
            }
        )

        # Aula OAuth configuration
        self.auth_base_url = "https://login.aula.dk"
        self.broker_url = "https://broker.unilogin.dk"
        self.app_redirect_uri = "https://app-private.aula.dk"
        self.client_id = "_99949a54b8b65423862aac1bf629599ed64231607a"
        self.scope = "aula-sensitive"

        # Session state
        self.code_verifier: str | None = None
        self.code_challenge: str | None = None
        self.state: str | None = None
        self.tokens: dict | None = None
        self.mitid_client: BrowserClient | None = None

    def generate_pkce_parameters(self) -> tuple[str, str]:
        """Generate PKCE parameters for OAuth 2.0."""
        code_verifier = (
            base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
        )
        challenge = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = base64.urlsafe_b64encode(challenge).decode("utf-8").rstrip("=")
        return code_verifier, code_challenge

    def generate_state(self) -> str:
        """Generate OAuth state parameter."""
        return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("utf-8").rstrip("=")

    async def step1_start_oauth_flow(self) -> str:
        """Step 1: Start OAuth authorization flow."""
        _LOGGER.info("Starting OAuth 2.0 authorization flow")

        try:
            self.code_verifier, self.code_challenge = self.generate_pkce_parameters()
            self.state = self.generate_state()

            auth_params = {
                "response_type": "code",
                "client_id": self.client_id,
                "scope": self.scope,
                "redirect_uri": self.app_redirect_uri,
                "state": self.state,
                "code_challenge": self.code_challenge,
                "code_challenge_method": "S256",
            }

            auth_url = f"{self.auth_base_url}/simplesaml/module.php/oidc/authorize.php"
            full_auth_url = f"{auth_url}?{urlencode(auth_params)}"

            _LOGGER.info("Visiting OAuth authorization URL")
            oauth_response = await self.client.get(full_auth_url)

            if oauth_response.is_redirect:
                redirect_url = oauth_response.headers.get("Location")
                _LOGGER.info(f"OAuth redirecting to SAML: {redirect_url[:80]}...")
                return redirect_url
            elif oauth_response.is_success:
                soup = BeautifulSoup(oauth_response.text, "html.parser")
                saml_form = soup.find("form")
                if saml_form and saml_form.get("action"):
                    return saml_form.get("action")
                raise OAuthError("OAuth authorization returned 200 but no redirect found")
            else:
                raise OAuthError(f"Unexpected OAuth response: {oauth_response.status_code}")

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during OAuth flow: {e}")

    async def step2_follow_redirect_to_mitid(self, start_url: str) -> dict:
        """Step 2: Follow the redirect chain to MitID."""
        _LOGGER.info("Following redirect chain to MitID")

        current_url = start_url
        redirect_count = 0
        max_redirects = 15

        try:
            while redirect_count < max_redirects:
                response = await self.client.get(current_url)
                redirect_count += 1
                _LOGGER.info(f"Redirect {redirect_count}: {response.status_code}")

                if response.is_success:
                    soup = BeautifulSoup(response.text, "html.parser")

                    if "broker.unilogin.dk" in str(response.url):
                        _LOGGER.info("Reached UniLogin broker - looking for MitID selection")
                        return await self._handle_broker_page(soup, response)

                    elif "mitid.dk" in str(response.url) or "nemlog-in" in str(response.url):
                        _LOGGER.info("Reached MitID page")
                        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
                        if not token_input:
                            raise SAMLError("Could not find RequestVerificationToken on MitID page")

                        return {
                            "verification_token": token_input["value"],
                            "mitid_url": str(response.url),
                        }
                    else:
                        raise SAMLError(f"Unexpected page reached: {response.url}")

                elif response.is_redirect:
                    if "Location" not in response.headers:
                        raise SAMLError("Redirect response missing Location header")
                    current_url = urljoin(str(current_url), response.headers["Location"])
                else:
                    raise SAMLError(f"Unexpected status code: {response.status_code}")

            raise SAMLError(f"Too many redirects ({max_redirects})")

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during redirect chain: {e}")

    async def _handle_broker_page(self, soup, response) -> dict:
        """Handle the broker page for MitID selection."""
        main_form = soup.find("form")
        if not main_form:
            raise SAMLError("No usable form found on broker page")

        action = main_form.get("action", "")
        if not action:
            raise SAMLError("Form has no action attribute")

        _LOGGER.info("Submitting MitID selection form")

        form_data = {}
        for inp in main_form.find_all("input"):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                form_data[name] = value

        form_data["selectedIdp"] = "nemlogin3"

        post_response = await self.client.post(action, data=form_data)

        if post_response.is_redirect:
            if "Location" in post_response.headers:
                current_url = post_response.headers["Location"]
                _LOGGER.info(f"Form submission redirected to: {current_url[:80]}...")
                return await self.step2_follow_redirect_to_mitid(current_url)

        raise SAMLError("Could not find working IdP selection method")

    async def step3_mitid_authentication(self, verification_token: str) -> str:
        """Step 3: Perform MitID authentication with the app."""
        _LOGGER.info("Starting MitID authentication (APP method)")

        post_url = "https://nemlog-in.mitid.dk/login/mitid/initialize"
        post_headers = {
            "accept": "*/*",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "origin": "https://nemlog-in.mitid.dk",
            "referer": "https://nemlog-in.mitid.dk/login/mitid",
            "x-requested-with": "XMLHttpRequest",
        }

        resp_init = await self.client.post(
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

        self.mitid_client = BrowserClient(client_hash, authentication_session_id, self.client)

        await self.mitid_client.initialize()

        available_authenticators = (
            await self.mitid_client.identify_as_user_and_get_available_authenticators(
                self.mitid_username
            )
        )

        _LOGGER.info(f"Available authenticators: {available_authenticators}")

        if "APP" in available_authenticators:
            await self.mitid_client.authenticate_with_app()
        else:
            raise MitIDError("APP authentication method not available for this user")

        authorization_code = (
            await self.mitid_client.finalize_authentication_and_get_authorization_code()
        )
        _LOGGER.info("MitID authentication code obtained")
        return authorization_code

    async def step4_complete_mitid_flow(
        self, verification_token: str, authorization_code: str
    ) -> dict:
        """Step 4: Complete MitID authentication and get SAML response."""
        _LOGGER.info("Completing MitID authentication flow")

        try:
            session_uuid = self.client.cookies.get("SessionUuid", "")
            challenge = self.client.cookies.get("Challenge", "")

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

            request = await self.client.post("https://nemlog-in.mitid.dk/login/mitid", data=params)

            soup = BeautifulSoup(request.text, features="html.parser")

            relay_state_input = soup.find("input", {"name": "RelayState"})
            saml_response_input = soup.find("input", {"name": "SAMLResponse"})

            if not relay_state_input or not saml_response_input:
                raise SAMLError("Could not find SAML data in MitID completion response")

            return {
                "relay_state": relay_state_input.get("value"),
                "saml_response": saml_response_input.get("value"),
            }

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during MitID completion: {e}")

    async def step5_saml_broker_flow(self, saml_data: dict) -> dict:
        """Step 5: Complete SAML broker authentication."""
        _LOGGER.info("Processing SAML broker flow")

        try:
            params = {
                "RelayState": saml_data["relay_state"],
                "SAMLResponse": saml_data["saml_response"],
            }

            broker_response = await self.client.post(
                "https://broker.unilogin.dk/auth/realms/broker/broker/nemlogin3/endpoint",
                data=params,
            )

            if not broker_response.is_redirect:
                raise SAMLError("No redirect from broker endpoint")

            action_url = broker_response.headers["Location"]
            final_request = await self.client.get(action_url)

            return await self._process_broker_response(final_request)

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during SAML broker flow: {e}")

    async def _process_broker_response(self, response) -> dict:
        """Process broker response and extract SAML for Aula."""
        _LOGGER.debug(f"Processing broker response from URL: {response.url}")

        soup = BeautifulSoup(response.text, "html.parser")

        form = soup.find("form")
        if not form:
            raise SAMLError("No form found in broker response")

        form_action = form.get("action")
        if not form_action:
            raise SAMLError("Form has no action attribute")

        form_data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                form_data[name] = value

        post_broker_response = await self.client.post(form_action, data=form_data)

        if not post_broker_response.is_redirect:
            raise SAMLError(
                f"No redirect from post-broker-login (status: {post_broker_response.status_code})"
            )

        after_url = post_broker_response.headers["Location"]
        after_response = await self.client.get(after_url)

        after_soup = BeautifulSoup(after_response.text, "html.parser")
        saml_form = after_soup.find("form")

        if not saml_form:
            raise SAMLError("No SAML form found in broker response")

        saml_response_input = saml_form.find("input", {"name": "SAMLResponse"})
        relay_state_input = saml_form.find("input", {"name": "RelayState"})

        if not saml_response_input:
            raise SAMLError("Could not find SAMLResponse")

        return {
            "final_saml_response": saml_response_input.get("value"),
            "final_relay_state": relay_state_input.get("value", "") if relay_state_input else "",
            "form_action": saml_form.get("action", ""),
        }

    async def step6_complete_aula_login(self, saml_data: dict) -> str:
        """Step 6: Complete Aula login with SAML response."""
        _LOGGER.info("Completing Aula login with SAML response")

        try:
            aula_saml_data = {
                "SAMLResponse": saml_data["final_saml_response"],
                "RelayState": saml_data["final_relay_state"],
            }

            saml_endpoint = saml_data.get(
                "form_action",
                "https://login.aula.dk/simplesaml/module.php/saml/sp/saml2-acs.php/uni-sp",
            )

            aula_response = await self.client.post(saml_endpoint, data=aula_saml_data)

            if not aula_response.is_redirect:
                raise OAuthError("No redirect from Aula SAML endpoint")

            return await self._follow_oauth_callback_redirects(aula_response.headers["Location"])

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during Aula login completion: {e}")

    async def _follow_oauth_callback_redirects(self, start_url: str) -> str:
        """Follow redirects to find the OAuth callback URL."""
        redirect_url = start_url
        redirect_count = 0
        max_redirects = 10

        while redirect_count < max_redirects:
            redirect_count += 1
            redirect_response = await self.client.get(redirect_url)

            # Check if this is the OAuth callback
            if self.app_redirect_uri in str(redirect_response.url) and "code=" in str(
                redirect_response.url
            ):
                _LOGGER.info("Found OAuth callback URL")
                return str(redirect_response.url)

            if "Location" in redirect_response.headers:
                location = redirect_response.headers["Location"]
                if self.app_redirect_uri in location and "code=" in location:
                    return location
                redirect_url = urljoin(str(redirect_response.url), location)
            elif redirect_response.is_success:
                final_url = str(redirect_response.url)
                if self.app_redirect_uri in final_url and "code=" in final_url:
                    return final_url
                raise OAuthError(f"Did not receive OAuth callback URL. Final: {final_url}")
            else:
                raise OAuthError(f"Unexpected status: {redirect_response.status_code}")

        raise OAuthError("Too many redirects without finding OAuth callback")

    async def step7_exchange_oauth_code(self, callback_url: str) -> dict:
        """Step 7: Exchange OAuth authorization code for tokens."""
        _LOGGER.info("Exchanging OAuth authorization code for tokens")

        try:
            parsed_url = urlparse(callback_url)
            query_params = parse_qs(parsed_url.query)

            if "code" not in query_params:
                raise OAuthError("No authorization code in callback URL")

            auth_code = query_params["code"][0]

            if "state" in query_params:
                returned_state = query_params["state"][0]
                if returned_state != self.state:
                    raise OAuthError("State parameter mismatch")

            token_url = f"{self.auth_base_url}/simplesaml/module.php/oidc/token.php"

            token_data = {
                "grant_type": "authorization_code",
                "code": auth_code,
                "client_id": self.client_id,
                "redirect_uri": self.app_redirect_uri,
                "code_verifier": self.code_verifier,
            }

            response = await self.client.post(
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

            self.tokens = tokens

            if expires_in := tokens.get("expires_in", 0):
                hours, remainder = divmod(int(expires_in), 3600)
                minutes = remainder // 60
                _LOGGER.info(f"Token obtained! Lifetime: {hours}h {minutes}m")

            return tokens

        except httpx.HTTPError as e:
            raise NetworkError(f"Network error during token exchange: {e}")
        except json.JSONDecodeError as e:
            raise OAuthError(f"Invalid token response format: {e}")

    async def authenticate(self) -> dict:
        """
        Execute the complete authentication flow.

        Returns:
            Dict containing success status and tokens
        """
        _LOGGER.info("=" * 60)
        _LOGGER.info("STARTING MITID AUTHENTICATION FLOW")
        _LOGGER.info("=" * 60)

        try:
            saml_redirect_url = await self.step1_start_oauth_flow()
            mitid_data = await self.step2_follow_redirect_to_mitid(saml_redirect_url)
            auth_code = await self.step3_mitid_authentication(mitid_data["verification_token"])
            saml_response_data = await self.step4_complete_mitid_flow(
                mitid_data["verification_token"], auth_code
            )
            broker_data = await self.step5_saml_broker_flow(saml_response_data)
            callback_url = await self.step6_complete_aula_login(broker_data)
            tokens = await self.step7_exchange_oauth_code(callback_url)

            _LOGGER.info("=" * 60)
            _LOGGER.info("AUTHENTICATION COMPLETED SUCCESSFULLY!")
            _LOGGER.info("=" * 60)

            return {"success": True, "tokens": tokens}

        except Exception as e:
            _LOGGER.error(f"Authentication flow failed: {e}")
            if isinstance(e, AulaAuthenticationError):
                raise
            raise AulaAuthenticationError(f"Authentication failed: {e}")

    @property
    def access_token(self) -> str | None:
        """Get the current access token."""
        return self.tokens.get("access_token") if self.tokens else None

    @property
    def refresh_token(self) -> str | None:
        """Get the current refresh token."""
        return self.tokens.get("refresh_token") if self.tokens else None

    def is_authenticated(self) -> bool:
        """Check if the client has valid tokens."""
        return bool(self.tokens and self.tokens.get("access_token"))

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
