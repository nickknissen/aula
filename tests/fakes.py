"""Test doubles that sit at the HttpClient seam."""

from dataclasses import dataclass, field
from typing import Any

from aula.http import HttpResponse


@dataclass
class Request:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] | None = None
    json: Any = None


class FakeHttpClient:
    """An HttpClient that answers by URL prefix and records every request.

    The longest matching prefix wins, so one Aula method can be routed apart from
    the rest of Aula. A route answers in the order given and then keeps repeating
    its last answer.
    """

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.cookies: dict[str, str] = {}
        self._routes: dict[str, list[HttpResponse]] = {}

    def route(self, prefix: str, *answers: HttpResponse) -> None:
        self._routes[prefix] = list(answers)

    def requests_to(self, prefix: str) -> list[Request]:
        return [request for request in self.requests if request.url.startswith(prefix)]

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> HttpResponse:
        self.requests.append(Request(method, url, dict(headers or {}), params, json))
        matches = [prefix for prefix in self._routes if url.startswith(prefix)]
        if not matches:
            raise AssertionError(f"No route for {method.upper()} {url}")
        answers = self._routes[max(matches, key=len)]
        return answers.pop(0) if len(answers) > 1 else answers[0]

    async def download_bytes(self, url: str, *, max_bytes: int | None = None) -> bytes:
        raise AssertionError(f"Unexpected download of {url}")

    def get_cookie(self, name: str) -> str | None:
        return self.cookies.get(name)

    async def close(self) -> None:
        pass
