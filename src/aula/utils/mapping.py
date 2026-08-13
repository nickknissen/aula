"""Helpers for reading nested values out of API responses."""

from typing import Any


def get_in(data: Any, path: str, default: Any = None) -> Any:
    """Read a dotted key path out of *data*.

    Aula sends an explicit ``null`` for objects it leaves empty, so a missing
    key and a present-but-null one mean the same thing here. Both give
    *default*, as does a value with an unexpected shape.

    >>> get_in({"profilePicture": {"url": "http://x"}}, "profilePicture.url")
    'http://x'
    >>> get_in({"profilePicture": None}, "profilePicture.url", default="")
    ''
    """
    for key in path.split("."):
        try:
            data = data[key]
        except KeyError, IndexError, TypeError:
            return default
    return default if data is None else data
