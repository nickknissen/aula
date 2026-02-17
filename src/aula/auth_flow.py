"""Standalone authentication helper that wires MitID auth to AulaApiClient."""

import logging
import time
from collections.abc import Callable

import qrcode

from .api_client import AulaApiClient
from .auth.exceptions import AulaAuthenticationError, OAuthError
from .auth.mitid_client import MitIDAuthClient
from .http_httpx import HttpxHttpClient
from .token_storage import TokenStorage

_LOGGER = logging.getLogger(__name__)


async def authenticate_and_create_client(
    mitid_username: str,
    token_storage: TokenStorage,
    on_qr_codes: Callable[[qrcode.QRCode, qrcode.QRCode], None] | None = None,
    on_login_required: Callable[[], None] | None = None,
) -> AulaApiClient:
    """Authenticate via MitID (or cached tokens) and return a ready-to-use client.

    Steps:
        1. Load cached tokens + cookies from storage.
        2. If expired/missing, run MitID auth and save tokens + cookies.
        3. Create HttpxHttpClient with the cookies.
        4. Create AulaApiClient and call init().
        5. Return the client.
    """
    auth_client = MitIDAuthClient(mitid_username=mitid_username, on_qr_codes=on_qr_codes)

    token_data = await token_storage.load()
    tokens_valid = False
    cookies: dict[str, str] = {}

    if token_data is not None:
        tokens = token_data.get("tokens", {})
        expires_at = tokens.get("expires_at")
        if tokens.get("access_token") and (expires_at is None or time.time() < expires_at):
            auth_client.tokens = tokens
            cookies = token_data.get("cookies", {})
            tokens_valid = True
            _LOGGER.info("Loaded cached authentication tokens")
        elif tokens.get("refresh_token"):
            _LOGGER.info("Cached tokens expired, attempting refresh")
            try:
                new_tokens = await auth_client.refresh_access_token(tokens["refresh_token"])
                cookies = token_data.get("cookies", {})
                await token_storage.save(
                    {
                        "timestamp": time.time(),
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "username": mitid_username,
                        "tokens": new_tokens,
                        "cookies": cookies,
                    }
                )
                tokens_valid = True
                _LOGGER.info("Token refresh successful, tokens saved")
            except (OAuthError, RuntimeError) as e:
                _LOGGER.warning("Token refresh failed, will require full authentication: %s", e)
        else:
            _LOGGER.info("Cached tokens are expired, no refresh token available")

    if not tokens_valid:
        _LOGGER.info("No valid tokens found, starting MitID authentication...")
        if on_login_required:
            on_login_required()

        try:
            await auth_client.authenticate()
            cookies = dict(auth_client.cookies)
            await token_storage.save(
                {
                    "timestamp": time.time(),
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "username": mitid_username,
                    "tokens": auth_client.tokens,
                    "cookies": cookies,
                }
            )
            _LOGGER.info("Authentication successful! Tokens saved.")
        except AulaAuthenticationError as e:
            _LOGGER.error("Authentication failed: %s", e)
            raise RuntimeError(f"MitID authentication failed: {e}") from e
        finally:
            await auth_client.close()
    else:
        await auth_client.close()

    access_token = auth_client.access_token
    if not access_token:
        raise RuntimeError("No access token available after authentication")

    http_client = HttpxHttpClient(cookies=cookies)
    client = AulaApiClient(http_client, access_token)
    await client.init()
    return client
