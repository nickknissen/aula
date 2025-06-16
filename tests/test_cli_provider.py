"""Tests for the provider CLI commands."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from aula.cli import cli
from aula.plugins.base import Provider, ProviderRegistry


# Test provider classes
class TestProvider1(Provider):
    """Test provider 1."""
    provider_id = "test_provider_1"
    name = "Test Provider 1"
    description = "First test provider"

    async def fetch_data(self, **kwargs):
        """Fetch test data."""
        return {"test": "data1"}

class TestProvider2(Provider):
    """Test provider 2."""
    provider_id = "test_provider_2"
    name = "Test Provider 2"
    description = "Second test provider"

    async def fetch_data(self, **kwargs):
        """Fetch test data."""
        return {"test": "data2"}

@pytest.fixture
def mock_providers():
    """Register test providers and clean up after."""
    # Register test providers
    registry = ProviderRegistry()
    registry.register(TestProvider1)
    registry.register(TestProvider2)

    yield

    # Clean up
    registry._providers = {}

@pytest.fixture
def mock_auth():
    """Mock the Aula authentication."""
    with patch('aula.cli.AulaApiClient') as mock_client:
        mock_instance = mock_client.return_value
        mock_instance._get_widget_auth_token.return_value = "test_auth_token"
        mock_instance.login = AsyncMock()
        yield mock_instance

@pytest.fixture
def cli_runner():
    """Return a CliRunner for testing CLI commands."""
    return CliRunner()

def test_provider_list_command(cli_runner: CliRunner, mock_providers):
    """Test the provider list command."""
    # Run the command
    result = cli_runner.invoke(cli, ["provider", "list"])

    # Check the output
    assert result.exit_code == 0
    assert "Available providers:" in result.output
    assert "test_provider_1" in result.output
    assert "Test Provider 1" in result.output
    assert "test_provider_2" in result.output
    assert "Test Provider 2" in result.output

@pytest.mark.asyncio
async def test_provider_fetch_command(cli_runner: CliRunner, mock_providers, mock_auth, tmp_path):
    """Test the provider fetch command."""
    # Create a test provider that returns known data
    class TestFetchProvider(Provider):
        """Test provider for fetch command."""
        provider_id = "test_fetch"
        name = "Test Fetch Provider"
        description = "Test provider for fetch command"

        async def fetch_data(self, **kwargs):
            """Return test data."""
            return {"test": "fetch_data", "kwargs": kwargs}

    # Register the test provider
    registry = ProviderRegistry()
    registry.register(TestFetchProvider)

    # Test output to stdout
    result = cli_runner.invoke(
        cli,
        ["--debug", "provider", "fetch", "test_fetch", "--param1", "value1"]
    )

    # Check the output
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["test"] == "fetch_data"
    assert output["kwargs"]["param1"] == "value1"

    # Test output to file
    output_file = tmp_path / "output.json"
    result = cli_runner.invoke(
        cli,
        ["provider", "fetch", "test_fetch", "-o", str(output_file)]
    )

    # Check the output file
    assert result.exit_code == 0
    assert output_file.exists()
    with open(output_file) as f:
        file_content = json.load(f)
    assert file_content["test"] == "fetch_data"

@pytest.mark.asyncio
async def test_provider_fetch_invalid_provider(cli_runner: CliRunner, mock_providers):
    """Test fetching from an invalid provider."""
    result = cli_runner.invoke(
        cli,
        ["provider", "fetch", "nonexistent_provider"]
    )

    # Check the error message
    assert result.exit_code != 0
    assert "No such provider" in result.output

@pytest.mark.asyncio
async def test_provider_fetch_error(cli_runner: CliRunner, mock_providers, mock_auth):
    """Test error handling in the fetch command."""
    # Create a test provider that raises an exception
    class ErrorProvider(Provider):
        """Test provider that raises an exception."""
        provider_id = "error_provider"
        name = "Error Provider"
        description = "Provider that raises an exception"

        async def fetch_data(self, **kwargs):
            """Raise an exception."""
            raise ValueError("Test error")

    # Register the test provider
    registry = ProviderRegistry()
    registry.register(ErrorProvider)

    # Run the command
    result = cli_runner.invoke(
        cli,
        ["provider", "fetch", "error_provider"]
    )

    # Check the error message
    assert result.exit_code != 0
    assert "Error fetching data from provider" in result.output
    assert "Test error" in result.output
