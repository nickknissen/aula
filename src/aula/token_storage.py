"""Token storage abstraction for Aula authentication tokens."""

import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


class TokenStorage(ABC):
    """Abstract base class for token storage backends."""

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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))
        # Restrict file permissions to owner-only on Unix systems
        if sys.platform != "win32":
            os.chmod(self._path, 0o600)
        _LOGGER.debug("Tokens saved to %s", self._path)
