"""
Aula Data Providers Plugin System

This module provides a pluggable system for Aula data providers.
"""

__all__ = [
    "HTTPClientMixin",
    "Provider",
    "ProviderRegistry",
]

# Import base classes
from .base import Provider, ProviderRegistry
from .http import HTTPClientMixin

# Import providers to register them with the provider registry
# Each provider must be imported here to be available
from .providers.biblioteket import BiblioteketProvider  # noqa: F401
from .providers.minuddannelse import MinUddanelseProvider  # noqa: F401
