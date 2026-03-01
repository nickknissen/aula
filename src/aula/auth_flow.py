"""Authentication helpers for creating AulaApiClient instances.

Provides two entry points:

- ``create_client``: Build a client from stored tokens and cookies.
  Uses ``access_token`` during init to establish a session, then cookies only.

- ``authenticate_and_create_client``: Run the full MitID auth flow (or
  load cached tokens) and return a ready client.  Used by the CLI.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import qrcode

from .api_client import AulaApiClient
from .auth.exceptions import MitIDAuthError, OAuthError
from .auth.mitid_client import MitIDAuthClient
from .const import CSRF_TOKEN_COOKIE
from .http import AulaAuthenticationError, HttpClient
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
            Must contain ``tokens.access_token`` and should include session
            cookies used for Aula API authentication.
        http_client: Optional HTTP client implementing the ``HttpClient``
            protocol. When *None*, an ``HttpxHttpClient`` is created with the
            session cookies from ``token_data``.

    Returns:
        A ready-to-use ``AulaApiClient`` (``init()`` has been called).
        After ``init()``, the access token is cleared and the client relies
        on session cookies established during initialization.

    Raises:
        ValueError: If ``token_data`` has no ``access_token`` (compatibility
            requirement for stored credential schema).
    """
    tokens = token_data.get("tokens", {})
    access_token = tokens.get("access_token")
    if not access_token:
        raise ValueError("No access_token found in token_data")

    cookies = token_data.get("cookies", {})
    # Csrfp-Token is expected from the restored cookie jar when available.
    csrf_token = cookies.get(CSRF_TOKEN_COOKIE)

    if http_client is None:
        http_client = HttpxHttpClient(cookies=cookies)

    client = AulaApiClient(http_client, access_token=access_token, csrf_token=csrf_token)
    await client.init()
    return client


async def authenticate(
    mitid_username: str,
    token_storage: TokenStorage | None = None,
    on_qr_codes: Callable[[qrcode.QRCode, qrcode.QRCode], None] | None = None,
    on_login_required: Callable[[], None] | None = None,
    httpx_client: httpx.AsyncClient | None = None,
    force_login: bool = False,
    on_identity_selected: Callable[[list[str]], Awaitable[int]] | None = None,
    auth_method: str = "app",
    on_token_digits: Callable[[], Awaitable[str]] | None = None,
    on_password: Callable[[], Awaitable[str]] | None = None,
) -> dict[str, Any]:
    """Authenticate via MitID (or cached tokens) and return credential data.

    This is the low-level entry point that returns raw token data.  Callers
    decide where to persist the result (file, HA ConfigEntry, etc.).

    Use :func:`create_client` to build an ``AulaApiClient`` from the returned
    dict, or :func:`authenticate_and_create_client` for a one-step convenience.

    Args:
        mitid_username: MitID username for authentication.
        token_storage: Optional storage backend for caching tokens.  When
            provided, cached tokens are loaded/saved automatically.  When
            *None*, a fresh MitID login is always performed.
        on_qr_codes: Callback for displaying QR codes during MitID flow.
        on_login_required: Callback invoked when fresh login is needed.
        httpx_client: Optional ``httpx.AsyncClient`` to use for the MitID
            auth flow.  When provided, the caller retains ownership and must
            close it.  Useful for Home Assistant's shared web session
            (``get_async_client(hass)``).

        force_login: When ``True``, bypass cached credentials and perform a
            fresh MitID login to restore a valid session cookie jar.
    Returns:
        Credential dict suitable for passing to :func:`create_client`.
        Contains ``tokens`` (with ``access_token`` used during init to
        establish the session) and ``cookies`` for Aula session auth.
    """
    async with MitIDAuthClient(
        mitid_username=mitid_username,
        on_qr_codes=on_qr_codes,
        httpx_client=httpx_client,
        on_identity_selected=on_identity_selected,
        auth_method=auth_method,
        on_token_digits=on_token_digits,
        on_password=on_password,
    ) as auth_client:
        token_data = (
            None if force_login else (await token_storage.load() if token_storage else None)
        )
        tokens_valid = False
        cookies: dict[str, str] = {}

        result_data: dict[str, Any] = {}

        if force_login:
            _LOGGER.info("Force login requested; skipping cached token reuse")

        if token_data is not None:
            tokens = token_data.get("tokens", {})
            expires_at = tokens.get("expires_at")
            if tokens.get("access_token") and (expires_at is None or time.time() < expires_at):
                auth_client.tokens = tokens
                cookies = token_data.get("cookies", {})
                result_data = token_data
                tokens_valid = True
                _LOGGER.info("Loaded cached authentication tokens")
            elif tokens.get("refresh_token"):
                _LOGGER.info("Cached tokens expired, attempting refresh")
                try:
                    new_tokens = await auth_client.refresh_access_token(tokens["refresh_token"])
                    cookies = token_data.get("cookies", {})
                    result_data = _build_token_data(mitid_username, new_tokens, cookies)
                    if token_storage:
                        await token_storage.save(result_data)
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
                result_data = _build_token_data(mitid_username, auth_client.tokens, cookies)
                if token_storage:
                    await token_storage.save(result_data)
                _LOGGER.info("Authentication successful! Tokens saved.")
            except MitIDAuthError as e:
                _LOGGER.error("Authentication failed: %s", e)
                raise RuntimeError(f"MitID authentication failed: {e}") from e

        access_token = auth_client.access_token
        if not access_token:
            raise RuntimeError("No access token available after authentication")

    return result_data


async def authenticate_and_create_client(
    mitid_username: str,
    token_storage: TokenStorage,
    on_qr_codes: Callable[[qrcode.QRCode, qrcode.QRCode], None] | None = None,
    on_login_required: Callable[[], None] | None = None,
    httpx_client: httpx.AsyncClient | None = None,
    on_identity_selected: Callable[[list[str]], Awaitable[int]] | None = None,
    auth_method: str = "app",
    on_token_digits: Callable[[], Awaitable[str]] | None = None,
    on_password: Callable[[], Awaitable[str]] | None = None,
) -> AulaApiClient:
    """Authenticate via MitID (or cached tokens) and return a ready-to-use client.

    Convenience wrapper combining :func:`authenticate` and :func:`create_client`.
    Used by the CLI.

    Args:
        mitid_username: MitID username for authentication.
        token_storage: Storage backend for caching tokens.
        on_qr_codes: Callback for displaying QR codes during MitID flow.
        on_login_required: Callback invoked when fresh login is needed.
        httpx_client: Optional ``httpx.AsyncClient`` for the auth flow.
        on_identity_selected: Callback for choosing between multiple identities.
    """
    token_data = await authenticate(
        mitid_username,
        token_storage,
        on_qr_codes,
        on_login_required,
        httpx_client,
        on_identity_selected=on_identity_selected,
        auth_method=auth_method,
        on_token_digits=on_token_digits,
        on_password=on_password,
    )
    try:
        return await create_client(token_data)
    except AulaAuthenticationError as err:
        _LOGGER.warning(
            "Cached session cookies were rejected (%s); retrying with fresh MitID login",
            err,
        )
        fresh_token_data = await authenticate(
            mitid_username,
            token_storage,
            on_qr_codes,
            on_login_required,
            httpx_client,
            force_login=True,
            on_identity_selected=on_identity_selected,
            auth_method=auth_method,
            on_token_digits=on_token_digits,
            on_password=on_password,
        )
        return await create_client(fresh_token_data)


def _build_token_data(
    username: str,
    tokens: dict[str, Any] | None,
    cookies: dict[str, str],
) -> dict[str, Any]:
    """Build the standard token data dict for storage."""
    return {
        "timestamp": time.time(),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "username": username,
        "tokens": tokens,
        "cookies": cookies,
    }
