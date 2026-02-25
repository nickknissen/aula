"""Tests for aula.http."""

import pytest

from aula.http import (
    AulaAuthenticationError,
    AulaConnectionError,
    AulaNotFoundError,
    AulaRateLimitError,
    AulaServerError,
    HttpRequestError,
    HttpResponse,
)


def test_http_response_json():
    resp = HttpResponse(status_code=200, data={"key": "val"})
    assert resp.json() == {"key": "val"}


def test_http_response_json_none():
    resp = HttpResponse(status_code=204, data=None)
    assert resp.json() is None


def test_raise_for_status_ok():
    resp = HttpResponse(status_code=200)
    resp.raise_for_status()  # should not raise


def test_raise_for_status_4xx():
    resp = HttpResponse(status_code=404)
    with pytest.raises(HttpRequestError) as exc_info:
        resp.raise_for_status()
    assert exc_info.value.status_code == 404


def test_raise_for_status_5xx():
    resp = HttpResponse(status_code=500)
    with pytest.raises(HttpRequestError) as exc_info:
        resp.raise_for_status()
    assert exc_info.value.status_code == 500


def test_http_request_error_message():
    err = HttpRequestError("Not Found", status_code=404)
    assert str(err) == "Not Found"
    assert err.status_code == 404


def test_http_response_default_headers():
    resp = HttpResponse(status_code=200)
    assert resp.headers == {}


# --- Exception hierarchy tests ---


def test_raise_for_status_401_raises_auth_error():
    resp = HttpResponse(status_code=401)
    with pytest.raises(AulaAuthenticationError) as exc_info:
        resp.raise_for_status()
    assert exc_info.value.status_code == 401


def test_raise_for_status_403_raises_auth_error():
    resp = HttpResponse(status_code=403)
    with pytest.raises(AulaAuthenticationError) as exc_info:
        resp.raise_for_status()
    assert exc_info.value.status_code == 403


def test_raise_for_status_429_raises_rate_limit_error():
    resp = HttpResponse(status_code=429)
    with pytest.raises(AulaRateLimitError) as exc_info:
        resp.raise_for_status()
    assert exc_info.value.status_code == 429


def test_raise_for_status_404_raises_not_found_error():
    resp = HttpResponse(status_code=404)
    with pytest.raises(AulaNotFoundError) as exc_info:
        resp.raise_for_status()
    assert exc_info.value.status_code == 404


def test_raise_for_status_500_raises_server_error():
    resp = HttpResponse(status_code=500)
    with pytest.raises(AulaServerError) as exc_info:
        resp.raise_for_status()
    assert exc_info.value.status_code == 500


def test_raise_for_status_502_raises_server_error():
    resp = HttpResponse(status_code=502)
    with pytest.raises(AulaServerError) as exc_info:
        resp.raise_for_status()
    assert exc_info.value.status_code == 502


def test_raise_for_status_503_raises_server_error():
    resp = HttpResponse(status_code=503)
    with pytest.raises(AulaServerError) as exc_info:
        resp.raise_for_status()
    assert exc_info.value.status_code == 503


def test_raise_for_status_400_raises_generic_error():
    """400 Bad Request should raise generic HttpRequestError, not a subclass."""
    resp = HttpResponse(status_code=400)
    with pytest.raises(HttpRequestError) as exc_info:
        resp.raise_for_status()
    assert type(exc_info.value) is HttpRequestError
    assert exc_info.value.status_code == 400


def test_raise_for_status_422_raises_generic_error():
    """422 Unprocessable Entity should raise generic HttpRequestError."""
    resp = HttpResponse(status_code=422)
    with pytest.raises(HttpRequestError) as exc_info:
        resp.raise_for_status()
    assert type(exc_info.value) is HttpRequestError


def test_all_exceptions_inherit_from_http_request_error():
    """All specific exceptions should be catchable as HttpRequestError."""
    resp_401 = HttpResponse(status_code=401)
    resp_429 = HttpResponse(status_code=429)
    resp_404 = HttpResponse(status_code=404)
    resp_500 = HttpResponse(status_code=500)

    for resp in [resp_401, resp_429, resp_404, resp_500]:
        with pytest.raises(HttpRequestError):
            resp.raise_for_status()


def test_connection_error_default_status_code():
    err = AulaConnectionError("timeout")
    assert err.status_code == 0
    assert str(err) == "timeout"


def test_connection_error_inherits_from_http_request_error():
    err = AulaConnectionError("timeout")
    assert isinstance(err, HttpRequestError)
