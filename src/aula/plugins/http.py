"""
HTTP client utilities for Aula data providers.
"""
import json
import logging
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


class HTTPClientMixin:
    """Mixin class for providers that make HTTP requests."""

    #: Base URL for the provider's API
    base_url: str

    #: Default headers to include in requests
    default_headers: dict[str, str] = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }

    def __init__(self, *args, **kwargs):
        """Initialize the HTTP client."""
        super().__init__(*args, **kwargs)
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def auth_headers(self) -> dict[str, str]:
        """Get authentication headers.

        Returns:
            Dictionary of authentication headers
        """
        return {
            'Authorization': f'Bearer {self.auth_token}',
            **self.default_headers
        }

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp ClientSession.

        Returns:
            aiohttp.ClientSession instance
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        **kwargs
    ) -> dict[str, Any]:
        """Make an HTTP request.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (will be appended to base_url)
            params: Query parameters
            headers: Request headers
            **kwargs: Additional arguments to pass to aiohttp

        Returns:
            Parsed JSON response as a dictionary

        Raises:
            aiohttp.ClientError: If the request fails
        """
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {**self.auth_headers, **(headers or {})}

        # Mask sensitive headers for logging
        log_headers = headers.copy()
        if 'Authorization' in log_headers:
            auth_val = log_headers['Authorization']
            if len(auth_val) > 15:  # Only mask if it looks like a real token
                log_headers['Authorization'] = f"{auth_val[:10]}...{auth_val[-5:]}"

        session = await self.get_session()

        logger.debug(
            "Making %s request to %s with params: %s and headers: %s",
            method,
            url,
            params,
            log_headers
        )

        try:
            async with session.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                **kwargs
            ) as response:
                response_text = await response.text()
                content_type = response.headers.get('content-type', '')
                
                logger.debug(
                    "Response from %s %s - Status: %d, Content-Length: %s, Content-Type: %s",
                    method,
                    url,
                    response.status,
                    response.headers.get('content-length', 'unknown'),
                    content_type
                )
                
                # Log response body for debugging (truncated)
                if response_text:
                    log_text = response_text[:500] + ('...' if len(response_text) > 500 else '')
                    logger.debug("Response body (truncated): %s", log_text)
                
                # Check for error status
                if response.status >= 400:
                    error_msg = f"HTTP {response.status} Error: {response.reason}"
                    if response_text:
                        try:
                            error_data = json.loads(response_text)
                            error_msg = f"{error_msg} - {error_data}"
                        except json.JSONDecodeError:
                            error_msg = f"{error_msg} - {response_text[:200]}"
                    logger.error(error_msg)
                    response.raise_for_status()

                # Parse response
                if 'application/json' in content_type and response_text.strip():
                    try:
                        return json.loads(response_text)
                    except json.JSONDecodeError as e:
                        logger.error("Failed to parse JSON response: %s", e)
                        logger.debug("Response text: %s", response_text)
                        return {'_error': 'Invalid JSON response', '_raw': response_text}
                elif response_text.strip():
                    return {'_raw': response_text}
                else:
                    return {'_empty': True}

        except aiohttp.ClientError as e:
            logger.error("Request to %s failed: %s", url, str(e), exc_info=True)
            raise
        except Exception as e:
            logger.error("Unexpected error during request to %s: %s", url, str(e), exc_info=True)
            raise aiohttp.ClientError(f"Unexpected error: {str(e)}") from e

    async def get(self, endpoint: str, params: Optional[dict[str, Any]] = None, **kwargs) -> dict[str, Any]:
        """Make a GET request.

        Args:
            endpoint: API endpoint
            params: Query parameters
            **kwargs: Additional arguments to pass to request()

        Returns:
            Parsed JSON response as a dictionary
        """
        return await self.request('GET', endpoint, params=params, **kwargs)

    async def post(self, endpoint: str, data: Optional[dict[str, Any]] = None, **kwargs) -> dict[str, Any]:
        """Make a POST request.

        Args:
            endpoint: API endpoint
            data: Request body data
            **kwargs: Additional arguments to pass to request()

        Returns:
            Parsed JSON response as a dictionary
        """
        return await self.request('POST', endpoint, json=data, **kwargs)
