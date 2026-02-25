"""Authentication helpers for creating AulaApiClient instances.

Provides two entry points:

- ``create_client``: Build a client from stored tokens and cookies.
  Use this when you already have valid credentials (e.g. Home Assistant
  integration startup).

- ``authenticate_and_create_client``: Run the full MitID auth flow (or
  load cached tokens) and return a ready client.  Used by the CLI.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

import qrcode

from .api_client import AulaApiClient
from .auth.exceptions import AulaAuthenticationError, OAuthError
from .auth.mitid_client import MitIDAuthClient
from .http import HttpClient
from .http_httpx import HttpxHttpClient
from .token_storage import TokenStorage

_LOGGER = logging.getLogger(__name__)


async def create_client(
    token_data: dict[str, Any],
    http_client: HttpClient | None = None,
) -> AulaApiClient:
    """Create an AulaApiClient from stored credentials.

    This is the preferred entry point for Home Assistant integrations and other
    callers that manage token storage themselves.  The ``token_data`` dict is
    the same opaque blob produced by ``TokenStorage.save()`` — callers should
    store it as-is and pass it back here without inspecting its contents.

    Args:
        token_data: Credential dict as returned by ``TokenStorage.load()``.
            Must contain ``tokens.access_token``; may contain session cookies.
        http_client: Optional HTTP client implementing the ``HttpClient``
            protocol.  When *None*, an ``HttpxHttpClient`` is created with the
            session cookies from ``token_data``.

    Returns:
        A ready-to-use ``AulaApiClient`` (``init()`` has been called).

    Raises:
        ValueError: If ``token_data`` has no ``access_token``.
    """
    tokens = token_data.get("tokens", {})
    access_token = tokens.get("access_token")
    if not access_token:
        raise ValueError("No access_token found in token_data")

    cookies = token_data.get("cookies", {})
    csrf_token = cookies.get("Csrfp-Token")

    if http_client is None:
        http_client = HttpxHttpClient(cookies=cookies)

    client = AulaApiClient(http_client, access_token, csrf_token=csrf_token)
    await client.init()
    return client


async def authenticate_and_create_client(
    mitid_username: str,
    token_storage: TokenStorage,
    on_qr_codes: Callable[[qrcode.QRCode, qrcode.QRCode], None] | None = None,
    on_login_required: Callable[[], None] | None = None,
) -> AulaApiClient:
    """Authenticate via MitID (or cached tokens) and return a ready-to-use client.

    Handles the full token lifecycle: load from cache, refresh if expired,
    or run the interactive MitID flow as a last resort.

    Args:
        mitid_username: MitID username for authentication.
        token_storage: Storage backend for caching tokens.
        on_qr_codes: Callback for displaying QR codes during MitID flow.
        on_login_required: Callback invoked when fresh login is needed.
    """
    async with MitIDAuthClient(
        mitid_username=mitid_username, on_qr_codes=on_qr_codes
    ) as auth_client:
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

        access_token = auth_client.access_token
        if not access_token:
            raise RuntimeError("No access token available after authentication")

    return await create_client({"tokens": {"access_token": access_token}, "cookies": cookies})
