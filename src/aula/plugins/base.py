"""
Base classes for Aula data providers.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="Provider")


class Provider(ABC):
    """Base class for all Aula data providers.

    Subclasses must implement the `fetch_data` method and define the `provider_id` class attribute.
    """

    #: Unique identifier for the provider (e.g., "biblioteket", "minuddannelse")
    provider_id: str = ""

    #: Human-readable name of the provider
    name: str = ""

    #: Description of the provider
    description: str = ""
    
    def __init_subclass__(cls, **kwargs):
        """Register the provider class when it's defined."""
        super().__init_subclass__(**kwargs)
        if cls.provider_id:  # Only register if provider_id is set
            ProviderRegistry.register(cls)

    def __init__(self, auth_token: str, **kwargs):
        """Initialize the provider with an Aula authentication token.

        Args:
            auth_token: Aula authentication token
            **kwargs: Provider-specific configuration that overrides config file
        """
        from ..config import config as app_config

        self.auth_token = auth_token

        # Get provider-specific config from the app config
        provider_config = app_config.get_provider_config(self.provider_id)

        # Update with any instance-specific overrides
        provider_config.update(kwargs)
        self.config = provider_config

    @abstractmethod
    async def fetch_data(self, **kwargs) -> dict[str, Any]:
        """Fetch data from the provider.

        Args:
            **kwargs: Provider-specific parameters

        Returns:
            Dict containing the fetched data
        """
        pass

    def __str__(self) -> str:
        return f"{self.name} ({self.provider_id})"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id='{self.provider_id}'>"


class ProviderRegistry:
    """Registry for managing provider classes.

    This class implements the singleton pattern to ensure there's only one
    registry instance throughout the application.
    """

    _instance = None
    _providers: dict[str, type[Provider]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def register(cls, provider_class: type[T]) -> type[T]:
        """Register a provider class.

        Args:
            provider_class: Provider class to register

        Returns:
            The registered provider class
        """
        logger.debug(f"Attempting to register provider class: {provider_class.__name__}")
        provider_id = getattr(provider_class, "provider_id", None)
        
        if not provider_id:
            logger.error(f"Provider class {provider_class.__name__} is missing 'provider_id' class attribute")
            raise ValueError("Provider class must define a 'provider_id' class attribute")

        logger.debug(f"Registering provider: id='{provider_id}', class={provider_class.__name__}")

        if provider_id in cls._providers:
            logger.warning("Overwriting provider with ID: %s", provider_id)

        cls._providers[provider_id] = provider_class
        logger.debug(f"Registered providers: {list(cls._providers.keys())}")
        return provider_class

    @classmethod
    def get_provider_class(cls, provider_id: str) -> Optional[type[Provider]]:
        """Get a provider class by ID.

        Args:
            provider_id: ID of the provider to get

        Returns:
            Provider class or None if not found
        """
        return cls._providers.get(provider_id.lower())

    @classmethod
    def get_providers(cls) -> dict[str, type[Provider]]:
        """Get all registered provider classes.

        Returns:
            Dictionary mapping provider IDs to provider classes
        """
        return dict(cls._providers)

    @classmethod
    def create_provider(cls, provider_id: str, auth_token: str, **kwargs) -> Provider:
        """Create an instance of a provider.

        Args:
            provider_id: ID of the provider to create
            auth_token: Aula authentication token
            **kwargs: Additional arguments to pass to the provider constructor

        Returns:
            Provider instance

        Raises:
            ValueError: If the provider ID is not registered
        """
        provider_class = cls.get_provider_class(provider_id.lower())
        if not provider_class:
            raise ValueError(f"Unknown provider: {provider_id}")
        return provider_class(auth_token, **kwargs)
