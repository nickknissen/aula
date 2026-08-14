import base64
import binascii
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .base import AulaDataClass

_LOGGER = logging.getLogger(__name__)


def decode_mu_deep_link(url: str | None) -> str | None:
    """Return the MinUddannelse page URL wrapped inside an opgave ``url``.

    An opgave's ``url`` is an SSO entry point of the form
    ``https://api.minuddannelse.net/aula/redirect/<id>/<base64>``. The widget
    never navigates to it directly; it submits it as a form with the Aula token
    in a hidden field, so fetching it server side lands on ``/Error/IngenAdgang``
    and the raw value is useless as a link.

    The last path segment is the base64 of the percent-encoded real page URL, so
    decoding it yields a link that opens the right week. Returns None whenever
    that does not hold, which keeps callers on plain text rather than handing out
    a broken link.
    """
    if not url:
        return None

    segment = url.rsplit("/", 1)[-1]
    if not segment:
        return None

    try:
        # validate=True rejects a segment that is not base64 at all, e.g. the
        # last path element of an ordinary URL, instead of decoding it to bytes
        # that only look like a result.
        raw = base64.b64decode(segment + "=" * (-len(segment) % 4), validate=True)
        decoded = urllib.parse.unquote(raw.decode("utf-8"))
    except binascii.Error, UnicodeDecodeError, ValueError:
        _LOGGER.debug("Could not decode Min Uddannelse deep link: %s", url)
        return None

    # Anything that is not an absolute http(s) URL is not a link we should show,
    # however cleanly it decoded.
    if not decoded.startswith(("http://", "https://")):
        _LOGGER.debug("Decoded Min Uddannelse deep link is not a URL: %s", url)
        return None

    return decoded


def _parse_dotnet_date(value: str | None) -> datetime | None:
    """Parse a .NET JSON date string like '/Date(1771196400000-0000)/'."""
    if not value:
        return None
    match = re.search(r"/Date\((\d+)([+-]\d{4})?\)/", value)
    if not match:
        return None
    return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC)


@dataclass
class MUTaskClass(AulaDataClass):
    id: int
    name: str
    subject_id: int
    subject_name: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MUTaskClass:
        return cls(
            _raw=data,
            id=data.get("id", 0),
            name=data.get("navn", ""),
            subject_id=data.get("fagId", 0),
            subject_name=data.get("fagNavn", ""),
        )


@dataclass
class MUTaskCourse(AulaDataClass):
    id: str
    name: str
    icon: str
    yearly_plan_id: str
    color: str | None
    url: str | None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MUTaskCourse:
        return cls(
            _raw=data,
            id=data.get("id", ""),
            name=data.get("navn", ""),
            icon=data.get("ikon", ""),
            yearly_plan_id=data.get("aarsplanId", ""),
            color=data.get("farve"),
            url=data.get("url"),
        )


@dataclass
class MUTask(AulaDataClass):
    id: str
    title: str
    task_type: str
    due_date: datetime | None
    weekday: str
    week_number: int
    is_completed: bool
    student_name: str
    unilogin: str
    url: str
    deep_link: str | None = None
    classes: list[MUTaskClass] = field(default_factory=list)
    course: MUTaskCourse | None = None
    student_count: int | None = None
    completed_count: int | None = None
    placement: str | None = None
    placement_time: str | None = None
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MUTask:
        classes = [MUTaskClass.from_dict(h) for h in data.get("hold", [])]
        forloeb = data.get("forloeb")
        return cls(
            _raw=data,
            id=data["id"],
            title=data.get("title", ""),
            task_type=data.get("opgaveType", ""),
            due_date=_parse_dotnet_date(data.get("afleveringsdato")),
            weekday=data.get("ugedag", ""),
            week_number=data.get("ugenummer", 0),
            is_completed=data.get("erFaerdig", False),
            student_name=data.get("kuvertnavn", ""),
            unilogin=data.get("unilogin", ""),
            url=data.get("url", ""),
            # ``url`` is kept exactly as Aula sent it; the usable link is derived.
            deep_link=decode_mu_deep_link(data.get("url")),
            classes=classes,
            course=MUTaskCourse.from_dict(forloeb) if forloeb else None,
            student_count=data.get("antalElever"),
            completed_count=data.get("antalFaerdige"),
            placement=data.get("placering"),
            placement_time=data.get("placeringTidspunkt"),
        )
