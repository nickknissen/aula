"""
Configuration management for Aula CLI and providers.
"""
from pathlib import Path
from typing import Any, Optional, TypeVar

import yaml

T = TypeVar('T')

class Config:
    """Configuration manager for Aula CLI and providers."""

    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize the configuration manager.

        Args:
            config_dir: Directory to store configuration files. If None, uses the default
                     directory (~/.config/aula on Unix-like systems).
        """
        if config_dir is None:
            self.config_dir = Path.home() / ".config" / "aula"
        else:
            self.config_dir = Path(config_dir)

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Main config file
        self.config_file = self.config_dir / "config.yaml"

        # Cache for loaded config
        self._config: dict[str, Any] = {}

        # Load existing config if it exists
        self.load()

    def load(self) -> None:
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, encoding='utf-8') as f:
                    self._config = yaml.safe_load(f) or {}
            except (yaml.YAMLError, OSError):
                # If there's an error loading the config, start with an empty one
                self._config = {}
        else:
            self._config = {}

    def save(self) -> None:
        """Save configuration to file."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(self._config, f, default_flow_style=False, sort_keys=False)
        except OSError as e:
            raise RuntimeError(f"Failed to save configuration to {self.config_file}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by dot-notation key.

        Args:
            key: Dot-notation key (e.g., 'providers.biblioteket.base_url')
            default: Default value if key is not found

        Returns:
            The configuration value or the default if not found
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value by dot-notation key.

        Args:
            key: Dot-notation key (e.g., 'providers.biblioteket.base_url')
            value: Value to set
        """
        keys = key.split('.')
        current = self._config

        # Navigate to the parent dict, creating nested dicts as needed
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]

        # Set the value
        current[keys[-1]] = value

        # Save the updated config
        self.save()

    def get_provider_config(self, provider_id: str) -> dict[str, Any]:
        """Get configuration for a specific provider.

        Args:
            provider_id: ID of the provider

        Returns:
            Dictionary of provider configuration
        """
        return self.get(f'providers.{provider_id}', {})

    def set_provider_config(self, provider_id: str, config: dict[str, Any]) -> None:
        """Set configuration for a specific provider.

        Args:
            provider_id: ID of the provider
            config: Dictionary of provider configuration
        """
        self.set(f'providers.{provider_id}', config)

    def get_credentials(self) -> dict[str, str]:
        """Get stored credentials.

        Returns:
            Dictionary containing 'username' and 'password' if available, empty dict otherwise
        """
        return self.get('auth', {})

    def set_credentials(self, username: str, password: str) -> None:
        """Store credentials.

        Args:
            username: Aula username/email
            password: Aula password
        """
        self.set('auth', {'username': username, 'password': password})

# Global config instance
config = Config()
