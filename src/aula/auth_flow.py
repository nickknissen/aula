"""Standalone authentication helper that wires MitID auth to AulaApiClient."""

import logging
import time

from .api_client import AulaApiClient
from .auth import AulaAuthenticationError, MitIDAuthClient
from .http_httpx import HttpxHttpClient
from .token_storage import TokenStorage

_LOGGER = logging.getLogger(__name__)


async def authenticate_and_create_client(
    mitid_username: str,
    token_storage: TokenStorage,
) -> AulaApiClient:
    """Authenticate via MitID (or cached tokens) and return a ready-to-use client.

    Steps:
        1. Load cached tokens + cookies from storage.
        2. If expired/missing, run MitID auth and save tokens + cookies.
        3. Create HttpxHttpClient with the cookies.
        4. Create AulaApiClient and call init().
        5. Return the client.
    """
    auth_client = MitIDAuthClient(mitid_username=mitid_username)

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
        else:
            _LOGGER.info("Cached tokens are expired")

    if not tokens_valid:
        _LOGGER.info("No valid tokens found, starting MitID authentication...")
        _LOGGER.info("Please approve the login request in your MitID app")

        try:
            await auth_client.authenticate()
            cookies = dict(auth_client.cookies)
            await token_storage.save({
                "timestamp": time.time(),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "username": mitid_username,
                "tokens": auth_client.tokens,
                "cookies": cookies,
            })
            _LOGGER.info("Authentication successful! Tokens saved.")
        except AulaAuthenticationError as e:
            _LOGGER.error("Authentication failed: %s", e)
            raise RuntimeError(f"MitID authentication failed: {e}") from e
        finally:
            await auth_client.close()

    access_token = auth_client.access_token
    if not access_token:
        raise RuntimeError("No access token available after authentication")

    http_client = HttpxHttpClient(cookies=cookies)
    client = AulaApiClient(http_client, access_token)
    await client.init()
    return client
