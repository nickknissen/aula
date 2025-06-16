"""Pytest configuration and fixtures for Aula provider tests."""
import os
import shutil
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from aula.config import Config


@pytest.fixture(scope="function")
def temp_config_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary configuration directory for tests."""
    # Create a temporary config directory
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Set environment variable to use this config directory
    old_env = os.environ.get("AULA_CONFIG_DIR")
    os.environ["AULA_CONFIG_DIR"] = str(config_dir)

    yield config_dir

    # Cleanup
    if old_env is not None:
        os.environ["AULA_CONFIG_DIR"] = old_env
    else:
        os.environ.pop("AULA_CONFIG_DIR", None)
    shutil.rmtree(config_dir, ignore_errors=True)

@pytest.fixture(scope="function")
def test_config(temp_config_dir: Path) -> Config:
    """Create a test configuration."""
    from aula.config import config as app_config
    # Clear any existing config
    app_config._config = {}
    return app_config

@pytest.fixture
def mock_auth_token() -> str:
    """Return a mock Aula authentication token."""
    return "test_auth_token_123"

@pytest.fixture
def mock_provider_config() -> dict[str, Any]:
    """Return a mock provider configuration."""
    return {
        "base_url": "https://api.example.com/v1",
        "timeout": 30,
        "retries": 3,
    }

@pytest.fixture
def mock_provider_response() -> dict[str, Any]:
    """Return a mock provider response."""
    return {
        "status": "success",
        "data": [
            {"id": 1, "name": "Test Item 1"},
            {"id": 2, "name": "Test Item 2"},
        ]
    }
