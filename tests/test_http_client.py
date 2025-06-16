"""Tests for the HTTP client mixin."""
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientResponseError, ClientSession

from aula.plugins.http import HTTPClientMixin


@pytest.mark.asyncio
async def test_http_client_get_success(mock_provider_response):
    """Test successful GET request."""
    # Create a mock session
    mock_session = AsyncMock(spec=ClientSession)
    mock_response = AsyncMock()
    mock_response.json.return_value = mock_provider_response
    mock_response.status = 200
    mock_session.get.return_value.__aenter__.return_value = mock_response

    # Create a test class that uses the mixin
    class TestClient(HTTPClientMixin):
        """Test client with HTTP mixin."""
        base_url = "https://api.example.com"

        def __init__(self, auth_token):
            """Initialize with auth token."""
            self.auth_token = auth_token
            HTTPClientMixin.__init__(self)

    # Initialize test client
    client = TestClient("test_token")

    # Patch the session
    with patch('aiohttp.ClientSession', return_value=mock_session):
        # Make the request
        result = await client.get("/test")

        # Check the result
        assert result == mock_provider_response

        # Check that the session was used correctly
        mock_session.get.assert_called_once_with(
            "https://api.example.com/test",
            headers={"Authorization": "Bearer test_token"},
            params=None,
            json=None,
            timeout=30
        )

@pytest.mark.asyncio
async def test_http_client_post_success():
    """Test successful POST request."""
    # Create a mock session
    mock_session = AsyncMock(spec=ClientSession)
    mock_response = AsyncMock()
    mock_response.json.return_value = {"status": "success"}
    mock_response.status = 201
    mock_session.post.return_value.__aenter__.return_value = mock_response

    # Create a test class that uses the mixin
    class TestClient(HTTPClientMixin):
        """Test client with HTTP mixin."""
        base_url = "https://api.example.com"

        def __init__(self, auth_token):
            """Initialize with auth token."""
            self.auth_token = auth_token
            HTTPClientMixin.__init__(self)

    # Initialize test client
    client = TestClient("test_token")

    # Test data
    test_data = {"key": "value"}

    # Patch the session
    with patch('aiohttp.ClientSession', return_value=mock_session):
        # Make the request
        result = await client.post("/test", json=test_data)

        # Check the result
        assert result == {"status": "success"}

        # Check that the session was used correctly
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args[1]
        assert call_args["url"] == "https://api.example.com/test"
        assert call_args["headers"]["Authorization"] == "Bearer test_token"
        assert call_args["json"] == test_data

@pytest.mark.asyncio
async def test_http_client_request_error():
    """Test handling of HTTP request errors."""
    # Create a test class that uses the mixin
    class TestClient(HTTPClientMixin):
        """Test client with HTTP mixin."""
        base_url = "https://api.example.com"

        def __init__(self, auth_token):
            """Initialize with auth token."""
            self.auth_token = auth_token
            HTTPClientMixin.__init__(self)

    # Initialize test client
    client = TestClient("test_token")

    # Patch the session to raise an error
    with patch('aiohttp.ClientSession') as mock_session:
        # Set up the mock to raise an error
        mock_session.return_value.__aenter__.return_value.get.side_effect = \
            ClientResponseError(
                status=404,
                request_info=None,
                history=(),
                headers={}
            )

        # Make the request and check that it raises the expected exception
        with pytest.raises(ClientResponseError) as exc_info:
            await client.get("/nonexistent")

        assert exc_info.value.status == 404
