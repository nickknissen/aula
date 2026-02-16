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


def _pad(s: str) -> str:
    pad_len = _BLOCK_SIZE - len(s) % _BLOCK_SIZE
    return s + pad_len * chr(pad_len)


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


class BrowserClient:
    """Async MitID browser client for handling the MitID authentication protocol."""

    def __init__(
        self,
        client_hash: str,
        authentication_session_id: str,
        http_client: httpx.AsyncClient,
    ):
        self.client = http_client
        self.client_hash = client_hash
        self.authentication_session_id = authentication_session_id

        # Storage for QR codes (can be accessed externally)
        self.qr1: qrcode.QRCode | None = None
        self.qr2: qrcode.QRCode | None = None
        self.otp_code: str | None = None
        self.status_message: str | None = None

    async def initialize(self):
        """Initialize the authentication session and retrieve service provider info."""
        r = await self.client.get(
            f"https://www.mitid.dk/mitid-core-client-backend/v1/authentication-sessions/{self.authentication_session_id}"
        )
        if not r.is_success:
            raise MitIDError(f"Failed to get authentication session: {r.status_code}")

        r_json = r.json()
        # This is all needed for flowValueProofs later on
        self.broker_security_context = r_json["brokerSecurityContext"]
        self.service_provider_name = r_json["serviceProviderName"]
        self.reference_text_header = r_json["referenceTextHeader"]
        self.reference_text_body = r_json["referenceTextBody"]
        self.status_message = f"Beginning login session for {self.service_provider_name}"
        _LOGGER.info(f"Beginning login session for {self.service_provider_name}")
        _LOGGER.debug(f"{self.reference_text_header}")
        _LOGGER.debug(f"{self.reference_text_body}")

    def get_current_qr_codes(self) -> tuple | None:
        """Get current QR codes for external display (e.g., GUI)."""
        if self.qr1 and self.qr2:
            return (self.qr1, self.qr2)
        return None

    def get_otp_code(self) -> str | None:
        """Get current OTP code if available."""
        return self.otp_code

    def _print_qr_codes_in_terminal(self, qr1, qr2) -> None:
        """Print QR codes as ASCII art in the terminal."""
        print("\n" + "=" * 60)
        print("SCAN THESE QR CODES WITH YOUR MITID APP")
        print("=" * 60)
        print("\nQR CODE 1 (Scan this first):")
        # Use qrcode's built-in terminal rendering with tty mode for Windows compatibility
        try:
            qr1.print_ascii(invert=True)
        except UnicodeEncodeError:
            # Fallback to tty mode (simple ASCII) for Windows console
            qr1.print_tty()

        print("\nQR CODE 2 (Scan this second):")
        try:
            qr2.print_ascii(invert=True)
        except UnicodeEncodeError:
            # Fallback to tty mode (simple ASCII) for Windows console
            qr2.print_tty()

        print("\n" + "=" * 60)
        print("Waiting for you to scan the QR codes...")
        print("=" * 60 + "\n")

    async def identify_as_user_and_get_available_authenticators(
        self, user_id: str
    ) -> dict[str, str]:
        """Identify as a user and get available authentication methods."""
        self.user_id = user_id
        r = await self.client.put(
            f"https://www.mitid.dk/mitid-core-client-backend/v1/authentication-sessions/{self.authentication_session_id}",
            json={"identityClaim": user_id},
        )

        if not r.is_success:
            r_json = r.json()
            error_code = r_json.get("errorCode", "")
            if r.is_client_error and error_code == "control.identity_not_found":
                raise MitIDError(f"User '{user_id}' does not exist")
            if r.is_client_error and error_code == "control.authentication_session_not_found":
                raise MitIDError("Authentication session not found")
            raise MitIDError(f"Failed to identify as user ({user_id}): HTTP {r.status_code}")

        r = await self.client.post(
            f"https://www.mitid.dk/mitid-core-client-backend/v2/authentication-sessions/{self.authentication_session_id}/next",
            json={"combinationId": ""},
        )

        if not r.is_success:
            raise MitIDError(
                f"Failed to get authenticators for user ({user_id}): HTTP {r.status_code}"
            )

        r_json = r.json()
        if (
            r_json["errors"]
            and r_json["errors"][0]["errorCode"] == "control.authenticator_cannot_be_started"
        ):
            error_text = r_json["errors"][0]["userMessage"]["text"]["text"]
            raise MitIDError(f"Authenticator cannot be started: {error_text}")

        self.current_authenticator_type = r_json["nextAuthenticator"]["authenticatorType"]
        self.current_authenticator_session_flow_key = r_json["nextAuthenticator"][
            "authenticatorSessionFlowKey"
        ]
        self.current_authenticator_eafe_hash = r_json["nextAuthenticator"]["eafeHash"]
        self.current_authenticator_session_id = r_json["nextAuthenticator"][
            "authenticatorSessionId"
        ]

        available_combinations = r_json["combinations"]
        available_authenticators = {}
        for combo in available_combinations:
            name = _COMBINATION_ID_TO_NAME.get(combo["id"])
            if name:
                available_authenticators[name] = combo["combinationItems"][0]["name"]

        return available_authenticators

    async def authenticate_with_app(self) -> None:
        """Authenticate using the MitID app (with QR code or OTP)."""
        await self.__select_authenticator("APP")

        r = await self.client.post(
            f"https://www.mitid.dk/mitid-code-app-auth/v1/authenticator-sessions/web/{self.current_authenticator_session_id}/init-auth",
            json={},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to request app login: HTTP {r.status_code}")

        r_json = r.json()
        if r_json.get("errorCode") == "auth.codeapp.authentication.parallel_sessions_detected":
            raise MitIDError(
                "Parallel app sessions detected. Please wait a few minutes before trying again."
            )

        poll_url = r_json["pollUrl"]
        ticket = r_json["ticket"]
        self.status_message = "Login request has been made, open your MitID app now"
        _LOGGER.info("Login request has been made, open your MitID app now")

        while True:
            r = await self.client.post(poll_url, json={"ticket": ticket})
            r_json = r.json()

            if not r.is_success or (r_json["status"] == "OK" and r_json["confirmation"] is True):
                if not r.is_success or r_json["status"] != "OK":
                    raise MitIDError("Login request was not accepted")
                break

            status = r_json["status"]

            if status == "timeout":
                await asyncio.sleep(0.5)
                continue

            if status == "channel_validation_otp":
                self.otp_code = r_json["channelBindingValue"]
                self.status_message = (
                    f"Please use the following OTP code in the app: {self.otp_code}"
                )
                _LOGGER.info(f"Please use the following OTP code in the app: {self.otp_code}")
                await asyncio.sleep(0.5)
                continue

            if status == "channel_validation_tqr":
                # Generate QR codes
                channel_binding = r_json["channelBindingValue"]
                half = len(channel_binding) // 2
                update_count = r_json["updateCount"]

                qr1 = qrcode.QRCode(border=1)
                qr1.add_data(
                    json.dumps(
                        {"v": 1, "p": 1, "t": 2, "h": channel_binding[:half], "uc": update_count},
                        separators=(",", ":"),
                    )
                )
                qr1.make()

                qr2 = qrcode.QRCode(border=1)
                qr2.add_data(
                    json.dumps(
                        {"v": 1, "p": 2, "t": 2, "h": channel_binding[half:], "uc": update_count},
                        separators=(",", ":"),
                    )
                )
                qr2.make()

                self.qr1 = qr1
                self.qr2 = qr2
                self.status_message = "Scan QR code with MitID app"

                # Render QR codes in terminal
                self._print_qr_codes_in_terminal(qr1, qr2)

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

        r_json = r.json()
        response = r_json["payload"]["response"]
        response_signature = r_json["payload"]["responseSignature"]

        # SRP protocol stages
        timer_1 = time.time()
        SRP = CustomSRP()
        A = SRP.SRPStage1()
        timer_1 = time.time() - timer_1

        r = await self.client.post(
            f"https://www.mitid.dk/mitid-code-app-auth/v1/authenticator-sessions/web/{self.current_authenticator_session_id}/init",
            json={"randomA": {"value": A}},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to init app protocol: HTTP {r.status_code}")

        timer_2 = time.time()
        init_json = r.json()
        srpSalt = init_json["srpSalt"]["value"]
        randomB = init_json["randomB"]["value"]

        m = hashlib.sha256()
        m.update(
            base64.b64decode(response) + self.current_authenticator_session_flow_key.encode("utf8")
        )
        password = m.hexdigest()

        m1 = SRP.SRPStage3(srpSalt, randomB, password, self.current_authenticator_session_id)

        unhashed_flow_value_proof = self.__create_flow_value_proof()
        m = hashlib.sha256()
        unhashed_flow_value_proof_key = "flowValues" + bytes_to_hex(SRP.K_bits)
        m.update(unhashed_flow_value_proof_key.encode("utf8"))
        flow_value_proof_key = m.digest()

        flow_value_proof = hmac.new(
            flow_value_proof_key, unhashed_flow_value_proof, hashlib.sha256
        ).hexdigest()

        timer_2 = time.time() - timer_2

        r = await self.client.post(
            f"https://www.mitid.dk/mitid-code-app-auth/v1/authenticator-sessions/web/{self.current_authenticator_session_id}/prove",
            json={"m1": {"value": m1}, "flowValueProof": {"value": flow_value_proof}},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to submit app response proof: HTTP {r.status_code}")

        timer_3 = time.time()
        m2 = r.json()["m2"]["value"]
        if not SRP.SRPStage5(m2):
            raise MitIDError("m2 could not be validated during proving of app response")
        auth_enc = base64.b64encode(SRP.AuthEnc(base64.b64decode(_pad(response_signature)))).decode(
            "ascii"
        )
        timer_3 = time.time() - timer_3

        front_end_processing_time = int((timer_1 + timer_2 + timer_3) * 1000)

        r = await self.client.post(
            f"https://www.mitid.dk/mitid-code-app-auth/v1/authenticator-sessions/web/{self.current_authenticator_session_id}/verify",
            json={
                "encAuth": auth_enc,
                "frontEndProcessingTime": front_end_processing_time,
            },
        )
        if not r.is_success:
            raise MitIDError(f"Failed to verify app response signature: HTTP {r.status_code}")

        r = await self.client.post(
            f"https://www.mitid.dk/mitid-core-client-backend/v2/authentication-sessions/{self.authentication_session_id}/next",
            json={"combinationId": ""},
        )
        if not r.is_success:
            raise MitIDError(f"Failed to prove app login: HTTP {r.status_code}")

        r_json = r.json()
        if r_json["errors"] and len(r_json["errors"]) > 0:
            raise MitIDError("Could not prove the app login. Please try again.")

        self.finalization_authentication_session_id = r_json["nextSessionId"]
        self.status_message = "App login was accepted, finalizing authentication"
        _LOGGER.info("App login was accepted, finalizing authentication")

    async def finalize_authentication_and_get_authorization_code(self) -> str:
        """Finalize authentication and retrieve the authorization code."""
        if not hasattr(self, "finalization_authentication_session_id"):
            raise MitIDError(
                "No finalization session ID set, complete an authentication flow first."
            )

        r = await self.client.put(
            f"https://www.mitid.dk/mitid-core-client-backend/v1/authentication-sessions/{self.finalization_authentication_session_id}/finalization"
        )
        if not r.is_success:
            raise MitIDError(f"Failed to retrieve authorization code: HTTP {r.status_code}")

        return r.json()["authorizationCode"]

    def __create_flow_value_proof(self) -> bytes:
        """Create flow value proof for authentication."""
        hashed_broker_security_context = hashlib.sha256(
            self.broker_security_context.encode("utf8")
        ).hexdigest()
        base64_reference_text_header = base64.b64encode(
            self.reference_text_header.encode("utf8")
        ).decode("ascii")
        base64_reference_text_body = base64.b64encode(
            self.reference_text_body.encode("utf8")
        ).decode("ascii")
        base64_service_provider_name = base64.b64encode(
            self.service_provider_name.encode("utf8")
        ).decode("ascii")
        parts = [
            self.current_authenticator_session_id,
            self.current_authenticator_session_flow_key,
            self.client_hash,
            self.current_authenticator_eafe_hash,
            hashed_broker_security_context,
            base64_reference_text_header,
            base64_reference_text_body,
            base64_service_provider_name,
        ]
        return ",".join(parts).encode()

    async def __select_authenticator(self, authenticator_type: str) -> None:
        """Select a specific authenticator type."""
        if (
            hasattr(self, "current_authenticator_type")
            and authenticator_type == self.current_authenticator_type
        ):
            return

        combination_id = _NAME_TO_COMBINATION_ID.get(authenticator_type)
        if not combination_id:
            raise MitIDError(f"No such authenticator name ({authenticator_type})")

        r = await self.client.post(
            f"https://www.mitid.dk/mitid-core-client-backend/v2/authentication-sessions/{self.authentication_session_id}/next",
            json={"combinationId": combination_id},
        )

        if not r.is_success:
            raise MitIDError(
                f"Failed to select authenticator for user ({self.user_id}): HTTP {r.status_code}"
            )

        r_json = r.json()
        if (
            r_json["errors"]
            and r_json["errors"][0]["errorCode"] == "control.authenticator_cannot_be_started"
        ):
            error_text = r_json["errors"][0]["userMessage"]["text"]["text"]
            raise MitIDError(f"Authenticator cannot be started: {error_text}")

        self.current_authenticator_type = r_json["nextAuthenticator"]["authenticatorType"]
        self.current_authenticator_session_flow_key = r_json["nextAuthenticator"][
            "authenticatorSessionFlowKey"
        ]
        self.current_authenticator_eafe_hash = r_json["nextAuthenticator"]["eafeHash"]
        self.current_authenticator_session_id = r_json["nextAuthenticator"][
            "authenticatorSessionId"
        ]

        if self.current_authenticator_type != authenticator_type:
            raise MitIDError(
                f"Could not select authenticator ({authenticator_type}), "
                f"got ({self.current_authenticator_type}) instead"
            )
