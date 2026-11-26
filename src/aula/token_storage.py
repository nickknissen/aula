"""Token storage abstraction for Aula authentication tokens."""

import asyncio
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .utils.atomic_write import write_json_atomic
from .utils.diagnostics import credential_logger

_LOGGER = credential_logger(__name__)


class TokenStorage(ABC):
    """Abstract base class for token storage backends.

    Methods are async to support future backends (e.g., remote/cloud storage)
    even though the file-based implementation runs its I/O in a worker thread.
    """

    @abstractmethod
    async def load(self) -> dict[str, Any] | None:
        """Load stored token data.

        Returns:
            The token data dict, or None if no valid data is available.
        """

    @abstractmethod
    async def save(self, data: dict[str, Any]) -> None:
        """Persist token data.

        Args:
            data: The token data dict to store.
        """


class FileTokenStorage(TokenStorage):
    """Store tokens as a JSON file on disk."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    async def load(self) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> dict[str, Any] | None:
        if not self._path.exists():
            _LOGGER.debug("Token file does not exist: %s", self._path)
            return None

        try:
            data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            _LOGGER.warning("Failed to read token file %s: %s", self._path, exc)
            return None

        if not isinstance(data, dict) or "tokens" not in data:
            _LOGGER.warning("Invalid token file format in %s", self._path)
            return None

        return data

    async def save(self, data: dict[str, Any]) -> None:
        await asyncio.to_thread(write_json_atomic, self._path, data)
        _LOGGER.debug("Tokens saved to %s", self._path)

    async def clear(self) -> bool:
        """Remove the stored tokens.

        Returns:
            True when a token file was removed, False when there was none.
        """
        try:
            self._path.unlink()
        except FileNotFoundError:
            return False
        _LOGGER.debug("Tokens removed from %s", self._path)
        return True
