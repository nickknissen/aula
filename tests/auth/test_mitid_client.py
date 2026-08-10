"""Tests for aula.auth.mitid_client — client construction and request headers."""

import httpx

from aula.auth.mitid_client import MitIDAuthClient
from aula.const import BROWSER_HEADERS, CHROME_VERSION, USER_AGENT


def test_browser_headers_applied_to_owned_client():
    """The UniLogin broker sits behind a bot filter that inspects these."""
    client = MitIDAuthClient(mitid_username="tester")

    headers = client._client.headers
    for header, value in BROWSER_HEADERS.items():
        assert headers[header] == value
    assert headers["User-Agent"] == USER_AGENT


def test_browser_headers_override_httpx_defaults():
    """httpx pre-populates Accept with */*, which must not survive."""
    client = MitIDAuthClient(mitid_username="tester")

    assert client._client.headers["Accept"].startswith("text/html")


def test_accept_encoding_left_to_httpx():
    """Advertising an encoding httpx cannot decode would break responses."""
    client = MitIDAuthClient(mitid_username="tester")

    assert "Accept-Encoding" not in BROWSER_HEADERS
    assert "zstd" not in client._client.headers["Accept-Encoding"]


def test_browser_headers_applied_to_injected_client():
    injected = httpx.AsyncClient()

    client = MitIDAuthClient(mitid_username="tester", httpx_client=injected)

    assert client._client is injected
    assert injected.headers["sec-ch-ua-platform"] == '"Windows"'
    assert injected.headers["User-Agent"] == USER_AGENT


def test_owned_client_enables_http2():
    """A client claiming to be Chrome that cannot speak HTTP/2 is a mismatch."""
    client = MitIDAuthClient(mitid_username="tester")

    pool = client._client._transport._pool  # type: ignore[attr-defined]
    assert pool._http2 is True


def test_sec_ch_ua_matches_user_agent_version():
    """Both carry the Chrome major version; drift between them is a bot signal."""
    assert f"Chrome/{CHROME_VERSION}.0.0.0" in USER_AGENT
    assert f'v="{CHROME_VERSION}"' in BROWSER_HEADERS["sec-ch-ua"]
    assert "Chromium" in BROWSER_HEADERS["sec-ch-ua"]
