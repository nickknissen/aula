"""Async MitID Browser Client for handling MitID authentication protocol."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time

import httpx
import qrcode

from ._utils import bytes_to_hex
from .exceptions import MitIDError
from .srp import CustomSRP

_LOGGER = logging.getLogger(__name__)

_BLOCK_SIZE = 16

# Authenticator mapping tables
_COMBINATION_ID_TO_NAME: dict[str, str] = {
    "S4": "APP",  # App + MitID chip
    "S3": "APP",
    "L2": "APP",
    "S1": "TOKEN",
}
_NAME_TO_COMBINATION_ID: dict[str, str] = {
    "APP": "S3",
    "TOKEN": "S1",
}


def _pad(s: str) -> str:
    pad_len = _BLOCK_SIZE - len(s) % _BLOCK_SIZE
    return s + pad_len * chr(pad_len)


def _extract_next_authenticator(response_json: dict) -> dict[str, str]:
    """Extract authenticator fields from a /next response."""
    next_auth = response_json["nextAuthenticator"]
    return {
        "type": next_auth["authenticatorType"],
        "session_flow_key": next_auth["authenticatorSessionFlowKey"],
        "eafe_hash": next_auth["eafeHash"],
        "session_id": next_auth["authenticatorSessionId"],
    }


def _check_authenticator_errors(response_json: dict) -> None:
    """Raise MitIDError if the response contains authenticator errors."""
    errors = response_json.get("errors")
    if errors and errors[0].get("errorCode") == "control.authenticator_cannot_be_started":
        error_text = errors[0]["userMessage"]["text"]["text"]
        raise MitIDError(f"Authenticator cannot be started: {error_text}")


class BrowserClient:
    """Async MitID browser client for handling the MitID authentication protocol."""

    def __init__(
        self,
        client_hash: str,
        authentication_session_id: str,
        http_client: httpx.AsyncClient,
    ):
        self._client = http_client
        self._client_hash = client_hash
        self._authentication_session_id = authentication_session_id

        # Authenticator state (populated after identify step)
        self._user_id: str | None = None
        self._authenticator_type: str | None = None
        self._authenticator_session_flow_key: str | None = None
        self._authenticator_eafe_hash: str | None = None
        self._authenticator_session_id: str | None = None
        self._finalization_session_id: str | None = None

        # Session context (populated after initialize)
        self._broker_security_context: str | None = None
        self._service_provider_name: str | None = None
        self._reference_text_header: str | None = None
        self._reference_text_body: str | None = None

        # Storage for QR codes (can be accessed externally)
        self.qr1: qrcode.QRCode | None = None
        self.qr2: qrcode.QRCode | None = None
        self.otp_code: str | None = None
        self.status_message: str | None = None

    def _base_url(self, version: int = 1) -> str:
        return f"https://www.mitid.dk/mitid-core-client-backend/v{version}/authentication-sessions/{self._authentication_session_id}"

    def _app_auth_url(self) -> str:
        return f"https://www.mitid.dk/mitid-code-app-auth/v1/authenticator-sessions/web/{self._authenticator_session_id}"

    def _set_authenticator_state(self, auth_info: dict[str, str]) -> None:
        """Update authenticator state from extracted response fields."""
        self._authenticator_type = auth_info["type"]
        self._authenticator_session_flow_key = auth_info["session_flow_key"]
        self._authenticator_eafe_hash = auth_info["eafe_hash"]
        self._authenticator_session_id = auth_info["session_id"]

    async def initialize(self) -> None:
        """Initialize the authentication session and retrieve service provider info."""
        r = await self._client.get(self._base_url())
        if not r.is_success:
            raise MitIDError(f"Failed to get authentication session: {r.status_code}")

        data = r.json()
        self._broker_security_context = data["brokerSecurityContext"]
        self._service_provider_name = data["serviceProviderName"]
        self._reference_text_header = data["referenceTextHeader"]
        self._reference_text_body = data["referenceTextBody"]

        self.status_message = f"Beginning login session for {self._service_provider_name}"
        _LOGGER.info("Beginning login session for %s", self._service_provider_name)
        _LOGGER.debug(self._reference_text_header)
        _LOGGER.debug(self._reference_text_body)

    def get_current_qr_codes(self) -> tuple | None:
        """Get current QR codes for external display (e.g., GUI)."""
        if self.qr1 and self.qr2:
            return (self.qr1, self.qr2)
        return None

    def get_otp_code(self) -> str | None:
        """Get current OTP code if available."""
        return self.otp_code

    async def identify_as_user_and_get_available_authenticators(
        self, user_id: str
    ) -> dict[str, str]:
        """Identify as a user and get available authentication methods."""
        self._user_id = user_id

        r = await self._client.put(
            self._base_url(),
            json={"identityClaim": user_id},
        )

        if not r.is_success:
            data = r.json()
            error_code = data.get("errorCode", "")
            if r.is_client_error and error_code == "control.identity_not_found":
                raise MitIDError(f"User '{user_id}' does not exist")
            if r.is_client_error and error_code == "control.authentication_session_not_found":
                raise MitIDError("Authentication session not found")
            raise MitIDError(f"Failed to identify as user ({user_id}): HTTP {r.status_code}")

        r = await self._client.post(
            self._base_url(version=2) + "/next",
            json={"combinationId": ""},
        )
        if not r.is_success:
            raise MitIDError(
                f"Failed to get authenticators for user ({user_id}): HTTP {r.status_code}"
            )

        data = r.json()
        _check_authenticator_errors(data)
        self._set_authenticator_state(_extract_next_authenticator(data))

        return {
            _COMBINATION_ID_TO_NAME[combo["id"]]: combo["combinationItems"][0]["name"]
            for combo in data["combinations"]
            if combo["id"] in _COMBINATION_ID_TO_NAME
        }

    async def authenticate_with_app(self) -> None:
        """Authenticate using the MitID app (with QR code or OTP)."""
        await self._select_authenticator("APP")

        r = await self._client.post(f"{self._app_auth_url()}/init-auth", json={})
        if not r.is_success:
            raise MitIDError(f"Failed to request app login: HTTP {r.status_code}")

        data = r.json()
        if data.get("errorCode") == "auth.codeapp.authentication.parallel_sessions_detected":
            raise MitIDError(
                "Parallel app sessions detected. Please wait a few minutes before trying again."
            )

        poll_url = data["pollUrl"]
        ticket = data["ticket"]
        self.status_message = "Login request has been made, open your MitID app now"
        _LOGGER.info("Login request has been made, open your MitID app now")

        response, response_signature = await self._poll_for_app_confirmation(poll_url, ticket)
        await self._perform_srp_handshake(response, response_signature)

    async def finalize_authentication_and_get_authorization_code(self) -> str:
        """Finalize authentication and retrieve the authorization code."""
        if self._finalization_session_id is None:
            raise MitIDError(
                "No finalization session ID set, complete an authentication flow first."
            )

        r = await self._client.put(
            f"https://www.mitid.dk/mitid-core-client-backend/v1/authentication-sessions/{self._finalization_session_id}/finalization"
        )
        if not r.is_success:
            raise MitIDError(f"Failed to retrieve authorization code: HTTP {r.status_code}")

        return r.json()["authorizationCode"]

    # -- Private helpers --

    async def _poll_for_app_confirmation(self, poll_url: str, ticket: str) -> tuple[str, str]:
        """Poll until the user confirms in the MitID app.

        Returns:
            Tuple of (response, response_signature) from the app payload.
        """
        while True:
            r = await self._client.post(poll_url, json={"ticket": ticket})
            data = r.json()

            if not r.is_success or (data["status"] == "OK" and data["confirmation"] is True):
                if not r.is_success or data["status"] != "OK":
                    raise MitIDError("Login request was not accepted")
                return data["payload"]["response"], data["payload"]["responseSignature"]

            status = data["status"]

            if status == "timeout":
                await asyncio.sleep(0.5)
                continue

            if status == "channel_validation_otp":
                self.otp_code = data["channelBindingValue"]
                self.status_message = (
                    f"Please use the following OTP code in the app: {self.otp_code}"
                )
                _LOGGER.info("Please use the following OTP code in the app: %s", self.otp_code)
                await asyncio.sleep(0.5)
                continue

            if status == "channel_validation_tqr":
                self._handle_qr_code_poll(data)
                await asyncio.sleep(1)
                continue

            if status == "channel_verified":
                self.status_message = (
                    "The OTP/QR code has been verified, now waiting user to approve login"
                )
                _LOGGER.info("The OTP/QR code has been verified, now waiting user to approve login")
                await asyncio.sleep(0.5)
                continue

            raise MitIDError(f"Unexpected poll status: {status}")

    def _handle_qr_code_poll(self, data: dict) -> None:
        """Generate and display QR codes from a TQR poll response."""
        channel_binding = data["channelBindingValue"]
        half = len(channel_binding) // 2
        update_count = data["updateCount"]

        self.qr1 = qrcode.QRCode(border=1)
        self.qr1.add_data(
            json.dumps(
                {"v": 1, "p": 1, "t": 2, "h": channel_binding[:half], "uc": update_count},
                separators=(",", ":"),
            )
        )
        self.qr1.make()

        self.qr2 = qrcode.QRCode(border=1)
        self.qr2.add_data(
            json.dumps(
                {"v": 1, "p": 2, "t": 2, "h": channel_binding[half:], "uc": update_count},
                separators=(",", ":"),
            )
        )
        self.qr2.make()

        self.status_message = "Scan QR code with MitID app"
        self._print_qr_codes_in_terminal(self.qr1, self.qr2)

    def _print_qr_codes_in_terminal(self, qr1: qrcode.QRCode, qr2: qrcode.QRCode) -> None:
        """Print QR codes as ASCII art in the terminal."""
        print("\n" + "=" * 60)
        print("SCAN THESE QR CODES WITH YOUR MITID APP")
        print("=" * 60)
        print("\nQR CODE 1 (Scan this first):")
        try:
            qr1.print_ascii(invert=True)
        except UnicodeEncodeError:
            qr1.print_tty()

        print("\nQR CODE 2 (Scan this second):")
        try:
            qr2.print_ascii(invert=True)
        except UnicodeEncodeError:
            qr2.print_tty()

        print("\n" + "=" * 60)
        print("Waiting for you to scan the QR codes...")
        print("=" * 60 + "\n")

    async def _perform_srp_handshake(self, response: str, response_signature: str) -> None:
        """Execute the full SRP handshake (init → prove → verify → next)."""
        timer_start = time.monotonic()

        assert self._authenticator_session_flow_key is not None
        assert self._authenticator_session_id is not None

        srp = CustomSRP()
        public_a = srp.srp_stage1()

        r = await self._client.post(
            f"{self._app_auth_url()}/init",
            json={"randomA": {"value": public_a}},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to init app protocol: HTTP {r.status_code}")

        init_data = r.json()
        srp_salt = init_data["srpSalt"]["value"]
        random_b = init_data["randomB"]["value"]

        password = hashlib.sha256(
            base64.b64decode(response) + self._authenticator_session_flow_key.encode("utf-8")
        ).hexdigest()

        m1 = srp.srp_stage3(srp_salt, random_b, password, self._authenticator_session_id)

        flow_value_proof = self._compute_flow_value_proof(srp.session_key_bytes)

        r = await self._client.post(
            f"{self._app_auth_url()}/prove",
            json={"m1": {"value": m1}, "flowValueProof": {"value": flow_value_proof}},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to submit app response proof: HTTP {r.status_code}")

        m2 = r.json()["m2"]["value"]
        if not srp.srp_stage5(m2):
            raise MitIDError("m2 could not be validated during proving of app response")

        auth_enc = base64.b64encode(
            srp.auth_enc(base64.b64decode(_pad(response_signature)))
        ).decode("ascii")

        front_end_time_ms = int((time.monotonic() - timer_start) * 1000)

        r = await self._client.post(
            f"{self._app_auth_url()}/verify",
            json={
                "encAuth": auth_enc,
                "frontEndProcessingTime": front_end_time_ms,
            },
        )
        if not r.is_success:
            raise MitIDError(f"Failed to verify app response signature: HTTP {r.status_code}")

        r = await self._client.post(
            self._base_url(version=2) + "/next",
            json={"combinationId": ""},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to prove app login: HTTP {r.status_code}")

        data = r.json()
        if data.get("errors"):
            raise MitIDError("Could not prove the app login. Please try again.")

        self._finalization_session_id = data["nextSessionId"]
        self.status_message = "App login was accepted, finalizing authentication"
        _LOGGER.info("App login was accepted, finalizing authentication")

    def _compute_flow_value_proof(self, session_key: bytes) -> str:
        """Create HMAC-SHA256 flow value proof using the SRP session key."""
        assert self._authenticator_session_id is not None
        assert self._authenticator_session_flow_key is not None
        assert self._authenticator_eafe_hash is not None
        assert self._broker_security_context is not None
        assert self._reference_text_header is not None
        assert self._reference_text_body is not None
        assert self._service_provider_name is not None

        proof_key = hashlib.sha256(
            ("flowValues" + bytes_to_hex(session_key)).encode("utf-8")
        ).digest()

        parts: list[str] = [
            self._authenticator_session_id,
            self._authenticator_session_flow_key,
            self._client_hash,
            self._authenticator_eafe_hash,
            hashlib.sha256(self._broker_security_context.encode("utf-8")).hexdigest(),
            base64.b64encode(self._reference_text_header.encode("utf-8")).decode("ascii"),
            base64.b64encode(self._reference_text_body.encode("utf-8")).decode("ascii"),
            base64.b64encode(self._service_provider_name.encode("utf-8")).decode("ascii"),
        ]
        payload = ",".join(parts).encode()

        return hmac.new(proof_key, payload, hashlib.sha256).hexdigest()

    async def _select_authenticator(self, authenticator_type: str) -> None:
        """Select a specific authenticator type."""
        if self._authenticator_type == authenticator_type:
            return

        combination_id = _NAME_TO_COMBINATION_ID.get(authenticator_type)
        if not combination_id:
            raise MitIDError(f"No such authenticator name ({authenticator_type})")

        r = await self._client.post(
            self._base_url(version=2) + "/next",
            json={"combinationId": combination_id},
        )
        if not r.is_success:
            raise MitIDError(
                f"Failed to select authenticator for user ({self._user_id}): HTTP {r.status_code}"
            )

        data = r.json()
        _check_authenticator_errors(data)
        self._set_authenticator_state(_extract_next_authenticator(data))

        if self._authenticator_type != authenticator_type:
            raise MitIDError(
                f"Could not select authenticator ({authenticator_type}), "
                f"got ({self._authenticator_type}) instead"
            )
