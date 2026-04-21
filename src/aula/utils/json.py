"""JSON serialization helpers for CLI output."""

import datetime
import enum
import json
from typing import Any

from aula.models.base import AulaDataClass


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime.datetime | datetime.date):
        return obj.isoformat()
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, AulaDataClass):
        return dict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def to_json(data: Any) -> str:
    """Serialize *data* to a JSON string.

    Handles ``datetime``, ``enum.Enum``, and ``AulaDataClass`` instances
    via a custom *default* handler.
    """
    return json.dumps(data, default=_default, ensure_ascii=False)
