"""Async MitID Browser Client for handling MitID authentication protocol."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable

import httpx
import qrcode

from ._utils import bytes_to_hex
from .exceptions import MitIDError, PasswordInvalidError, TokenInvalidError
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


def _pkcs7_pad(s: str) -> str:
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
        on_qr_codes: Callable[[qrcode.QRCode, qrcode.QRCode], None] | None = None,
    ):
        self._client = http_client
        self._client_hash = client_hash
        self._authentication_session_id = authentication_session_id
        self._on_qr_codes = on_qr_codes

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

    def _code_token_auth_url(self) -> str:
        return f"https://www.mitid.dk/mitid-code-token-auth/v1/authenticator-sessions/{self._authenticator_session_id}"

    def _password_auth_url(self) -> str:
        return f"https://www.mitid.dk/mitid-password-auth/v1/authenticator-sessions/{self._authenticator_session_id}"

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
        _LOGGER.info("MitID session initialized for service: %s", self._service_provider_name)
        _LOGGER.debug(
            "Reference text: %s — %s", self._reference_text_header, self._reference_text_body
        )

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
        _LOGGER.info("Waiting for MitID app approval")

        response, response_signature = await self._poll_for_app_confirmation(poll_url, ticket)
        await self._perform_srp_handshake(response, response_signature)

    async def authenticate_with_token_and_password(self, token_digits: str, password: str) -> None:
        """Authenticate using a MitID hardware token (TOTP) and password."""
        await self._authenticate_token_phase(token_digits)
        await self._authenticate_password_phase(password)
        self.status_message = "Token + password login accepted, finalizing authentication"
        _LOGGER.info("MitID token + password authentication successful")

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

            if not r.is_success:
                raise MitIDError("Login request was not accepted")

            if data["status"] == "OK" and data["confirmation"] is True:
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
                _LOGGER.debug("OTP channel validation requested")
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
                _LOGGER.debug("Channel verified, awaiting user approval")
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
        if self._on_qr_codes:
            self._on_qr_codes(self.qr1, self.qr2)

    async def _perform_srp_handshake(self, response: str, response_signature: str) -> None:
        """Execute the full SRP handshake (init → prove → verify → next)."""
        timer_start = time.monotonic()

        if self._authenticator_session_flow_key is None or self._authenticator_session_id is None:
            raise MitIDError("SRP handshake requires authenticator session to be established")

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
            srp.auth_enc(base64.b64decode(_pkcs7_pad(response_signature)))
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
        _LOGGER.info("MitID app authentication successful")

    async def _authenticate_token_phase(self, token_digits: str) -> None:
        """Execute the TOTP code token authentication phase."""
        timer_start = time.monotonic()
        await self._select_authenticator("TOKEN")

        srp = CustomSRP()
        public_a = srp.srp_stage1()

        r = await self._client.post(
            f"{self._code_token_auth_url()}/codetoken-init",
            json={"randomA": {"value": public_a}},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to init token protocol: HTTP {r.status_code}")

        init_data = r.json()
        srp_salt = init_data["srpSalt"]["value"]
        random_b = init_data["randomB"]["value"]

        # For TOKEN auth the SRP password is the hex-encoded flow key
        password = self._authenticator_session_flow_key.encode("utf-8").hex()

        m1 = srp.srp_stage3(srp_salt, random_b, password, self._authenticator_session_id)

        flow_value_proof = self._compute_flow_value_proof(
            srp.session_key_bytes, proof_key_prefix="OTP" + token_digits
        )

        front_end_time_ms = int((time.monotonic() - timer_start) * 1000)

        r = await self._client.post(
            f"{self._code_token_auth_url()}/codetoken-prove",
            json={
                "m1": {"value": m1},
                "flowValueProof": {"value": flow_value_proof},
                "frontEndProcessingTime": front_end_time_ms,
            },
        )
        if not r.is_success:
            raise MitIDError(f"Failed to submit token proof: HTTP {r.status_code}")

        r = await self._client.post(
            self._base_url(version=2) + "/next",
            json={"combinationId": ""},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to advance after token phase: HTTP {r.status_code}")

        data = r.json()
        errors = data.get("errors")
        if errors:
            error_code = errors[0].get("errorCode", "")
            if "TOTP_INVALID" in error_code:
                raise TokenInvalidError("The token code was rejected. Please try again.")
            raise MitIDError(f"Token authentication error: {error_code}")

        self._set_authenticator_state(_extract_next_authenticator(data))
        if self._authenticator_type != "PASSWORD":
            raise MitIDError(
                f"Expected PASSWORD authenticator after token phase, got {self._authenticator_type}"
            )

    async def _authenticate_password_phase(self, password: str) -> None:
        """Execute the MitID password authentication phase."""
        timer_start = time.monotonic()

        if self._authenticator_type != "PASSWORD":
            raise MitIDError("Password phase requires PASSWORD authenticator to be active")

        srp = CustomSRP()
        public_a = srp.srp_stage1()

        r = await self._client.post(
            f"{self._password_auth_url()}/init",
            json={"randomA": {"value": public_a}},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to init password protocol: HTTP {r.status_code}")

        init_data = r.json()
        pbkdf2_salt = init_data["pbkdf2Salt"]["value"]
        srp_salt = init_data["srpSalt"]["value"]
        random_b = init_data["randomB"]["value"]

        # Derive the SRP password using PBKDF2 (offloaded to avoid blocking the event loop)
        derived = await asyncio.to_thread(
            hashlib.pbkdf2_hmac, "sha256", password.encode(), bytes.fromhex(pbkdf2_salt), 20000, 32
        )
        srp_password = derived.hex()

        m1 = srp.srp_stage3(srp_salt, random_b, srp_password, self._authenticator_session_id)

        flow_value_proof = self._compute_flow_value_proof(srp.session_key_bytes)

        front_end_time_ms = int((time.monotonic() - timer_start) * 1000)

        r = await self._client.post(
            f"{self._password_auth_url()}/password-prove",
            json={
                "m1": {"value": m1},
                "flowValueProof": {"value": flow_value_proof},
                "frontEndProcessingTime": front_end_time_ms,
            },
        )
        if not r.is_success:
            raise MitIDError(f"Failed to submit password proof: HTTP {r.status_code}")

        r = await self._client.post(
            self._base_url(version=2) + "/next",
            json={"combinationId": ""},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to advance after password phase: HTTP {r.status_code}")

        data = r.json()
        errors = data.get("errors")
        if errors:
            error_code = errors[0].get("errorCode", "")
            if "PASSWORD_INVALID" in error_code or "psd2" in error_code:
                raise PasswordInvalidError("The password was rejected. Please try again.")
            raise MitIDError(f"Password authentication error: {error_code}")

        self._finalization_session_id = data["nextSessionId"]

    def _compute_flow_value_proof(
        self, session_key: bytes, proof_key_prefix: str = "flowValues"
    ) -> str:
        """Create HMAC-SHA256 flow value proof using the SRP session key."""
        required_fields = {
            "authenticator_session_id": self._authenticator_session_id,
            "authenticator_session_flow_key": self._authenticator_session_flow_key,
            "authenticator_eafe_hash": self._authenticator_eafe_hash,
            "broker_security_context": self._broker_security_context,
            "reference_text_header": self._reference_text_header,
            "reference_text_body": self._reference_text_body,
            "service_provider_name": self._service_provider_name,
        }
        missing = [k for k, v in required_fields.items() if v is None]
        if missing:
            raise MitIDError(f"Missing required auth state: {', '.join(missing)}")

        proof_key = hashlib.sha256(
            (proof_key_prefix + bytes_to_hex(session_key)).encode("utf-8")
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
