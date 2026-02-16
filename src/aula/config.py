"""Configuration management for Aula CLI."""

import json
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
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file."""
    ensure_config_dir()
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except OSError as e:
        click.echo(f"Error saving configuration: {e}", err=True)
