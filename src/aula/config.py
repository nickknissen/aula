"""Configuration management for Aula CLI."""

import contextlib
import json
import os
from pathlib import Path
from typing import Any

import click

CONFIG_DIR = Path.home() / ".config" / "aula"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_TOKEN_FILE = CONFIG_DIR / "tokens.json"


def ensure_config_dir() -> None:
    """Ensure the configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    """Load configuration from file."""
    ensure_config_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except OSError, json.JSONDecodeError:
            return {}
    return {}


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to a file only the owner can read."""
    ensure_config_dir()
    try:
        fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            # The mode given to os.open applies only when it creates the file.
            with contextlib.suppress(OSError):
                os.fchmod(fd, 0o600)
            json.dump(config, f, indent=2)
    except OSError as e:
        click.echo(f"Error saving configuration: {e}", err=True)
