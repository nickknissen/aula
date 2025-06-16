"""Tests for the provider discovery system."""
import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from aula.plugins.base import Provider, ProviderRegistry
from aula.plugins.discovery import discover_providers

# Create a test provider class for discovery tests
class DiscoverableTestProvider(Provider):
    """A test provider for discovery tests."""
    provider_id = "discoverable_test_provider"
    name = "Discoverable Test Provider"
    description = "A test provider for discovery"
    
    async def fetch_data(self, **kwargs):
        """Fetch test data."""
        return {"test": "discoverable_data"}

# Create a test module with a provider
test_module_code = """
""""Test module with a provider for discovery tests."""

from aula.plugins.base import Provider

class TestModuleProvider(Provider):
    """A test provider in a module."""
    provider_id = "module_test_provider"
    name = "Module Test Provider"
    description = "A test provider in a module"
    
    async def fetch_data(self, **kwargs):
        """Fetch test data."""
        return {"test": "module_data"}
"""

@pytest.fixture
def temp_providers_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary directory with test provider modules."""
    # Create a temporary package directory
    temp_pkg = tmp_path / "test_providers_pkg"
    temp_pkg.mkdir()
    
    # Create __init__.py
    (temp_pkg / "__init__.py").write_text(""""""Test providers package."""""")
    
    # Create a test provider module
    (temp_pkg / "test_provider.py").write_text(test_module_code)
    
    # Add the temporary directory to the Python path
    sys.path.insert(0, str(tmp_path))
    
    yield temp_pkg
    
    # Cleanup
    sys.path.remove(str(tmp_path))

def test_discover_providers():
    """Test that providers can be discovered and registered."""
    # Clear the provider registry
    registry = ProviderRegistry()
    registry._providers = {}
    
    # Mock importlib to return our test modules
    mock_module = MagicMock()
    mock_module.TestModuleProvider = DiscoverableTestProvider
    
    with patch('importlib.import_module', return_value=mock_module):
        # Call the discovery function
        discover_providers(['test_module'])
    
    # Check that the provider was registered
    provider_class = registry.get_provider(DiscoverableTestProvider.provider_id)
    assert provider_class is not None
    assert provider_class.provider_id == DiscoverableTestProvider.provider_id

def test_discover_providers_from_package(temp_providers_dir):
    """Test that providers can be discovered from a package."""
    # Clear the provider registry
    registry = ProviderRegistry()
    registry._providers = {}
    
    # Import the test module to register the provider
    import test_providers_pkg.test_provider
    
    # Check that the provider was registered
    provider_class = registry.get_provider("module_test_provider")
    assert provider_class is not None
    assert provider_class.provider_id == "module_test_provider"
    assert provider_class.name == "Module Test Provider"

@patch('aula.plugins.discovery.logger')
def test_discover_providers_import_error(mock_logger):
    """Test that import errors during discovery are logged but don't fail."""
    # Clear the provider registry
    registry = ProviderRegistry()
    registry._providers = {}
    
    # Mock importlib to raise an ImportError
    with patch('importlib.import_module') as mock_import:
        mock_import.side_effect = ImportError("Test import error")
        
        # Call the discovery function
        discover_providers(['nonexistent_module'])
    
    # Check that the error was logged
    mock_logger.warning.assert_called()
    assert "Failed to import module" in mock_logger.warning.call_args[0][0]
    
    # Check that no providers were registered
    assert len(registry.get_providers()) == 0
