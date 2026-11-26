"""Test doubles that sit at the HttpClient seam."""

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from aula.const import API_URL
from aula.http import HttpResponse


@dataclass
class Request:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] | None = None
    json: Any = None

    @property
    def wire_url(self) -> str:
        """The URL as it goes out, with params added to the query string."""
        if not self.params:
            return self.url
        encoded = urlencode(
            [
                (key, _wire_value(item))
                for key, value in self.params.items()
                for item in (value if isinstance(value, list | tuple) else [value])
            ]
        )
        return f"{self.url}{'&' if '?' in self.url else '?'}{encoded}"

    @property
    def aula_method(self) -> str | None:
        """The Aula method this request calls."""
        if not self.url.startswith(API_URL):
            return None
        return self.query.get("method")

    @property
    def query(self) -> dict[str, Any]:
        """The query string as Aula receives it: text values, a list for a ``[]`` key."""
        return {
            key: values if key.endswith("[]") or len(values) > 1 else values[0]
            for key, values in parse_qs(urlparse(self.wire_url).query).items()
        }


def _wire_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def ok(data: Any = None) -> HttpResponse:
    """Aula's answer to a call that worked."""
    return HttpResponse(200, {"status": {"code": 0, "message": "OK"}, "data": data})


def rejected(code: int, sub_code: int | None = None, *, status_code: int = 200) -> HttpResponse:
    """Aula's answer to a call it refused, with its status code and sub-code."""
    status: dict[str, Any] = {"code": code}
    if sub_code is not None:
        status["subCode"] = sub_code
    return HttpResponse(status_code, {"status": status, "data": None})


def http_status(
    status_code: int, data: Any = None, headers: dict[str, str] | None = None
) -> HttpResponse:
    """A bare HTTP answer, such as a 410 or a 503 from in front of Aula."""
    return HttpResponse(status_code, data, dict(headers or {}))


class FakeHttpClient:
    """An HttpClient that answers by Aula method or URL prefix and records every request.

    An Aula method route wins over a prefix route. Among prefix routes the longest
    match wins, so one URL can be routed apart from the rest. A route answers in the
    order given and then keeps repeating its last answer.
    """

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.cookies: dict[str, str] = {}
        self._routes: dict[str, list[HttpResponse]] = {}
        self._aula_routes: dict[str, list[HttpResponse]] = {}

    def route(self, prefix: str, *answers: HttpResponse) -> None:
        self._routes[prefix] = list(answers)

    def aula(self, method: str, *answers: HttpResponse) -> None:
        """Answer calls to the Aula method ``method``, on any API version."""
        self._aula_routes[method] = list(answers)

    def requests_to(self, prefix: str) -> list[Request]:
        return [request for request in self.requests if request.wire_url.startswith(prefix)]

    def calls(self, method: str) -> list[Request]:
        """The requests that called the Aula method ``method``."""
        return [request for request in self.requests if request.aula_method == method]

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> HttpResponse:
        request = Request(method, url, dict(headers or {}), params, json)
        self.requests.append(request)
        answers = self._aula_routes.get(request.aula_method or "")
        if answers is None:
            matches = [prefix for prefix in self._routes if request.wire_url.startswith(prefix)]
            if not matches:
                raise AssertionError(f"No route for {method.upper()} {url}")
            answers = self._routes[max(matches, key=len)]
        return answers.pop(0) if len(answers) > 1 else answers[0]

    async def download_bytes(self, url: str, *, max_bytes: int | None = None) -> bytes:
        raise AssertionError(f"Unexpected download of {url}")

    def get_cookie(self, name: str) -> str | None:
        return self.cookies.get(name)

    def reset_cookies(self, cookies: dict[str, str]) -> None:
        self.cookies = dict(cookies)

    async def close(self) -> None:
        pass
