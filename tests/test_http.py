"""Tests for aula.http."""

import pytest

from aula.http import HttpRequestError, HttpResponse


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
