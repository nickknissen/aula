import logging
from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass

_LOGGER = logging.getLogger(__name__)


@dataclass
class PresenceLocation(AulaDataClass):
    """Where a child physically is, as reported by the presence endpoints.

    Aula sends this as an object, not a string: the Android app models it as
    ``PresenceLocationDto {long Id, string Name, string Description, string
    Symbol}``. The live payload carries more keys than that (time and date
    intervals, weekday masks), so the four the official client reads are named
    here and the rest stay in ``_raw``.
    """

    id: int | None = None
    name: str = ""
    description: str = ""
    symbol: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PresenceLocation:
        location_id = data.get("id")
        try:
            location_id = int(location_id) if location_id is not None else None
        except TypeError, ValueError:
            _LOGGER.warning("Non-numeric location id received: %s", location_id)
            location_id = None

        return cls(
            _raw=data,
            id=location_id,
            name=data.get("name") or "",
            description=data.get("description") or "",
            symbol=data.get("symbol") or "",
        )

    @classmethod
    def parse(cls, value: Any) -> PresenceLocation | None:
        """Build a location from whatever the API sent, or None if it sent nothing.

        A bare string is accepted as the name. No response is known to use that
        shape, but it costs nothing to keep older or unseen payloads working.
        """
        if value is None:
            return None
        if isinstance(value, dict):
            return cls.from_dict(value)
        if isinstance(value, str):
            return cls(name=value) if value else None

        _LOGGER.warning("Unexpected location value received: %r", value)
        return None
