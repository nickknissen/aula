import httpx
import pytest

from aula.http import AulaConnectionError, DownloadTooLargeError, HttpRequestError
from aula.http_httpx import HttpxHttpClient

API_URL = "https://www.aula.dk/api/v25/?method=profiles.getProfilesByLogin&access_token=secret"
DOWNLOAD_URL = "https://media.aula.dk/file.pdf?signature=secret"


def _client_failing_with(error: type[httpx.TransportError]) -> HttpxHttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error("[Errno -3] Try again", request=request)

    return HttpxHttpClient(httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _client_serving(response: httpx.Response) -> HttpxHttpClient:
    return HttpxHttpClient(
        httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
    )


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


@pytest.mark.asyncio
async def test_download_without_max_bytes_returns_the_whole_body():
    client = _client_serving(httpx.Response(200, content=b"x" * 100_000))

    assert await client.download_bytes(DOWNLOAD_URL) == b"x" * 100_000


@pytest.mark.asyncio
async def test_download_returns_a_file_of_exactly_max_bytes():
    client = _client_serving(httpx.Response(200, content=b"12345678"))

    assert await client.download_bytes(DOWNLOAD_URL, max_bytes=8) == b"12345678"


@pytest.mark.asyncio
async def test_download_refuses_a_too_large_content_length_without_reading_the_body():
    async def body():
        raise AssertionError("the body was read")
        yield b""

    client = _client_serving(httpx.Response(200, headers={"Content-Length": "9"}, content=body()))

    with pytest.raises(DownloadTooLargeError) as exc_info:
        await client.download_bytes(DOWNLOAD_URL, max_bytes=8)

    assert exc_info.value.max_bytes == 8
    assert not isinstance(exc_info.value, HttpRequestError)


@pytest.mark.asyncio
async def test_download_stops_reading_once_the_body_passes_max_bytes():
    """Without a Content-Length, the size is only known while streaming."""
    sent = []

    async def body():
        for chunk in (b"1234", b"5678", b"9", b"never sent"):
            sent.append(chunk)
            yield chunk

    client = _client_serving(httpx.Response(200, content=body()))

    with pytest.raises(DownloadTooLargeError) as exc_info:
        await client.download_bytes(DOWNLOAD_URL, max_bytes=8)

    assert sent == [b"1234", b"5678", b"9"]
    assert str(exc_info.value) == "Download from media.aula.dk is larger than 8 bytes"
