"""Tests for the provider registry."""
import pytest

from aula.plugins.base import Provider, ProviderRegistry


class TestProvider(Provider):
    """Test provider for registry tests."""
    provider_id = "test_provider"
    name = "Test Provider"
    description = "A test provider"

    async def fetch_data(self, **kwargs):
        """Fetch test data."""
        return {"test": "data"}

def test_register_provider():
    """Test that a provider can be registered and retrieved."""
    # Clear any existing providers
    registry = ProviderRegistry()
    registry._providers = {}

    # Register the provider
    registry.register(TestProvider)

    # Check that the provider was registered
    assert TestProvider.provider_id in registry._providers
    assert registry._providers[TestProvider.provider_id] is TestProvider

    # Check that get_provider returns the correct class
    provider_class = registry.get_provider(TestProvider.provider_id)
    assert provider_class is TestProvider

    # Check that get_providers returns the correct providers
    providers = registry.get_providers()
    assert len(providers) == 1
    assert providers[TestProvider.provider_id] is TestProvider

def test_register_duplicate_provider():
    """Test that registering a duplicate provider raises an error."""
    registry = ProviderRegistry()
    registry._providers = {}

    # Register the provider once
    registry.register(TestProvider)

    # Try to register it again
    with pytest.raises(ValueError, match=f"Provider with ID '{TestProvider.provider_id}' already registered"):
        registry.register(TestProvider)

def test_get_nonexistent_provider():
    """Test that getting a non-existent provider returns None."""
    registry = ProviderRegistry()
    registry._providers = {}

    # Try to get a non-existent provider
    provider = registry.get_provider("nonexistent_provider")
    assert provider is None

def test_provider_registry_singleton():
    """Test that ProviderRegistry is a singleton."""
    registry1 = ProviderRegistry()
    registry2 = ProviderRegistry()

    # Both instances should be the same object
    assert registry1 is registry2

    # Changes to one should affect the other
    registry1._providers["test"] = "test"
    assert "test" in registry2._providers
