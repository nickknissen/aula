import httpx
import pytest

from aula.http import AulaConnectionError, HttpRequestError
from aula.http_httpx import HttpxHttpClient

API_URL = "https://www.aula.dk/api/v25/?method=profiles.getProfilesByLogin&access_token=secret"


def _client_failing_with(error: type[httpx.TransportError]) -> HttpxHttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error("[Errno -3] Try again", request=request)

    return HttpxHttpClient(httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
async def test_request_raises_connection_error_for_network_failures(error):
    """Callers handle HttpRequestError; a raw httpx error skips their retry path."""
    client = _client_failing_with(error)

    with pytest.raises(AulaConnectionError) as exc_info:
        await client.request("get", API_URL)

    assert isinstance(exc_info.value, HttpRequestError)
    assert isinstance(exc_info.value.__cause__, error)
    assert exc_info.value.status_code == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
async def test_download_raises_connection_error_for_network_failures(error):
    """Attachment downloads fail the same way when the network drops."""
    client = _client_failing_with(error)

    with pytest.raises(AulaConnectionError) as exc_info:
        await client.download_bytes("https://media.aula.dk/file.pdf")

    assert isinstance(exc_info.value.__cause__, error)


@pytest.mark.asyncio
async def test_connection_error_names_the_host_but_not_the_query():
    """The message lands in logs, and the query string can carry credentials."""
    client = _client_failing_with(httpx.ConnectError)

    with pytest.raises(AulaConnectionError) as exc_info:
        await client.request("get", API_URL)

    assert str(exc_info.value) == "Could not reach www.aula.dk: [Errno -3] Try again"


@pytest.mark.asyncio
async def test_connection_error_names_the_error_type_when_httpx_gives_no_message():
    """A bare timeout has an empty message, which would leave the log line blank."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    client = HttpxHttpClient(httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(AulaConnectionError, match="Could not reach www.aula.dk: ReadTimeout"):
        await client.request("get", API_URL)
