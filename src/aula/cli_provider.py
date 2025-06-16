"""
CLI commands for Aula CLI provider commands.
"""

import asyncio
import datetime
import functools
import importlib.util
import json
import logging
from pathlib import Path
from typing import Any, Optional

import click

from aula.plugins import Provider, ProviderRegistry

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("aula_provider.log")],
)
logger = logging.getLogger(__name__)

# Register built-in providers
try:
    # Use importlib to check if providers are available
    if importlib.util.find_spec("aula.plugins.providers.biblioteket"):
        from aula.plugins.providers.biblioteket import BiblioteketProvider  # noqa: F401
        ProviderRegistry.register(BiblioteketProvider)
    
    if importlib.util.find_spec("aula.plugins.providers.minuddannelse"):
        from aula.plugins.providers.minuddannelse import MinUddannelseProvider  # noqa: F401
        ProviderRegistry.register(MinUddannelseProvider)
except ImportError as e:
    logger.warning("Failed to import built-in providers: %s", e)

__all__ = ["provider_cli", "register_provider_commands"]

# Type variable for async functions
T = Any

# Decorator to run async functions within Click commands
def async_cmd(f: callable) -> callable:
    """Run async functions within Click commands."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapper


# Custom types
JsonDict = dict[str, Any]

# Default output directory for exports
DEFAULT_OUTPUT_DIR = Path.cwd() / "aula_exports"


async def get_auth_token(ctx: click.Context) -> str:
    """Get Aula authentication token from the context.

    Args:
        ctx: Click context object

    Returns:
        str: Authentication token

    Raises:
        click.UsageError: If not authenticated and cannot authenticate
    """
    # Try to get the client from context first
    client = ctx.obj.get("client")

    # If no client in context, create a new one
    if client is None:
        # Import here to avoid circular imports
        from .cli import _get_client

        client = await _get_client(ctx)

    # Ensure we're logged in
    if not await client.is_logged_in():
        click.echo("Not authenticated. Logging in...", err=True)
        await client.login()

    # Get the auth token from the client's session
    auth_header = client._session.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise click.UsageError("Failed to get authentication token. Please log in first.")

    return auth_header.replace("Bearer ", "")


async def get_provider(provider_id: str, auth_token: str) -> Provider:
    """Get a provider instance by ID.

    Args:
        provider_id: The ID of the provider to get
        auth_token: Authentication token for the provider

    Returns:
        Provider: An instance of the requested provider

    Raises:
        click.UsageError: If the provider ID is unknown
    """
    click.echo(f"Getting provider class for ID: {provider_id}", err=True)
    provider_class = ProviderRegistry.get_provider_class(provider_id)

    if not provider_class:
        available = ", ".join(ProviderRegistry.get_available_providers())
        click.echo(f"Available providers: {available}", err=True)
        raise click.UsageError(f"Unknown provider: {provider_id}")

    click.echo(f"Creating provider instance for {provider_class.__name__}", err=True)
    try:
        provider = ProviderRegistry.create_provider(provider_id, auth_token)
        click.echo(f"Provider initialized: {provider}", err=True)
        return provider
    except Exception as e:
        click.echo(f"Error creating provider {provider_id}: {e}", err=True)
        import traceback
        click.echo(traceback.format_exc(), err=True)
        raise


def format_json(data: Any, *, pretty: bool = True) -> str:
    """Format data as JSON string.

    Args:
        data: The data to format as JSON
        pretty: Whether to pretty-print the output
    """
    kwargs = {
        "ensure_ascii": False,
        "indent": 2 if pretty else None,
        "default": lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o),
    }
    return json.dumps(data, **kwargs)


async def save_output(data: Any, output_file: Optional[Path] = None) -> Path:
    """Save data to a file.

    Args:
        data: The data to save
        output_file: Optional output file path. If not provided, a default path will be used.

    Returns:
        Path: The path to the saved file

    Raises:
        ValueError: If data is None or empty
        IOError: If there's an error writing the file
    """
    if data is None:
        raise ValueError("No data provided to save")

    # Create output directory if needed
    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = DEFAULT_OUTPUT_DIR / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "output.json"

    click.echo(f"Saving output to: {output_file.absolute()}", err=True)
    click.echo(f"Output file parent exists: {output_file.parent.exists()}", err=True)

    try:
        # Ensure parent directories exist
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Debug output
        click.echo(f"Parent directory permissions: {oct(output_file.parent.stat().st_mode)[-3:]}", err=True)

        # Handle different data types with appropriate serialization
        if isinstance(data, (dict, list)):
            json_str = json.dumps(data, indent=2)
            await asyncio.to_thread(output_file.write_text, json_str, encoding="utf-8")
        else:
            await asyncio.to_thread(output_file.write_text, str(data), encoding="utf-8")

        return output_file

    except Exception as e:
        click.echo(f"Error saving output to {output_file}: {e}", err=True)
        import traceback
        click.echo(traceback.format_exc(), err=True)
        raise


@click.group(name="provider", help="Manage and query Aula data providers")
def provider_cli():
    """Aula data provider commands."""
    pass


@provider_cli.command("list")
@click.pass_context
@async_cmd
async def list_providers(ctx: click.Context):
    """List all available data providers with detailed information."""
    click.echo("Debug: Starting list_providers", err=True)

    # Get all registered providers
    providers = ProviderRegistry.get_providers()
    if not providers:
        click.echo("No providers found in registry. Checking if providers are imported...", err=True)
        # Try to manually import providers to see if that helps
        try:
            import aula.plugins.providers.biblioteket  # noqa: F401
            import aula.plugins.providers.minuddannelse  # noqa: F401
            providers = ProviderRegistry.get_providers()
        except ImportError as e:
            click.echo(f"Error importing provider modules: {e}", err=True)

    if not providers:
        click.echo("No providers available. Please check your installation and imports.")
        return

    click.echo("\nAvailable data providers:")
    for provider_id, provider_class in sorted(providers.items()):
        try:
            click.echo(f"\n{provider_id}:")
            click.echo(f"  Class: {provider_class.__name__}")
            click.echo(f"  Module: {provider_class.__module__}")
            click.echo(f"  Name: {getattr(provider_class, 'name', 'N/A')}")
            if hasattr(provider_class, 'description') and provider_class.description:
                click.echo(f"  Description: {provider_class.description}")
            try:
                click.echo(f"  File: {inspect.getfile(provider_class)}")
            except (TypeError, OSError):
                click.echo("  File: Could not determine source file")
        except Exception as e:
            click.echo(f"\nError getting info for provider {provider_id}: {e}", err=True)
            import traceback
            click.echo(traceback.format_exc(), err=True)


@provider_cli.command("fetch")
@click.argument("provider_id")
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help=("Output file path (default: ./aula_exports/<timestamp>/<provider_id>.json)"),
)
@click.option(
    "--pretty/--no-pretty",
    is_flag=True,
    default=True,
    help="Pretty-print JSON output",
    show_default=True,
)
@click.option(
    "--child-id",
    "-c",
    "child_ids",
    multiple=True,
    help="Filter by child ID (can be used multiple times)",
)
@click.option(
    "--institution-id",
    "-i",
    "institution_ids",
    multiple=True,
    help=("Filter by institution ID (can be used multiple times)"),
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug output",
    default=False,
)
@click.pass_context
@async_cmd
async def fetch_provider(
    ctx: click.Context,
    provider_id: str,
    output_file: Optional[Path],
    pretty: bool,
    child_ids: list[str],
    institution_ids: list[str],
    debug: bool = False,
    **kwargs,
):
    """Fetch data from a provider.

    Args:
        ctx: Click context
        provider_id: ID of the provider to fetch data from
        output_file: Output file path (optional)
        pretty: Whether to pretty-print JSON output
        child_ids: List of child IDs to filter by
        institution_ids: List of institution IDs to filter by
        debug: Enable debug output
    """
    # Configure logging level
    if debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    if debug:
        ctx.obj["debug"] = True
        logger.info("Debug mode enabled")

    try:
        # Get authentication token
        logger.info("Getting auth token...")
        auth_token = await get_auth_token(ctx)
        if not auth_token:
            logger.error("Failed to get authentication token")
            raise click.UsageError(
                "Authentication failed. Please check your credentials."
            ) from None

        logger.debug("Auth token obtained successfully")

        # Get the provider instance
        logger.info("Initializing provider: %s", provider_id)
        try:
            provider = await get_provider(provider_id, auth_token)
            logger.info("Provider initialized: %s", provider.__class__.__name__)
            logger.debug("Provider details: %r", provider)
        except Exception as e:
            logger.error("Failed to initialize provider: %s", str(e), exc_info=debug)
            raise click.UsageError(f"Failed to initialize provider '{provider_id}': {str(e)}")

        # Prepare parameters
        params = {}
        if child_ids:
            logger.info("Filtering by child IDs: %s", child_ids)
            params['children'] = list(child_ids)

        if institution_ids:
            logger.info("Filtering by institution IDs: %s", institution_ids)
            params['institutions'] = list(institution_ids)

        logger.debug("Final request parameters: %s", params)

        # Fetch data from the provider
        logger.info("Fetching data from provider...")
        try:
            logger.debug("Calling provider.fetch_data() with params: %s", params)
            data = await provider.fetch_data(**params)
            logger.info("Data fetch completed successfully")

            if data is None:
                logger.warning("Provider returned no data")
            else:
                logger.debug("Data type: %s", type(data).__name__)
                if hasattr(data, 'keys'):
                    logger.debug("Data keys: %s", list(data.keys()))
                if hasattr(data, '__len__'):
                    logger.debug("Data length: %d", len(data))

                # Log a sample of the data
                sample = str(data)[:500] + ('...' if len(str(data)) > 500 else '')
                logger.debug("Data sample: %s", sample)

        except Exception as e:
            logger.error("Error fetching data: %s", str(e), exc_info=debug)
            raise click.ClickException(f"Failed to fetch data: {e}") from e

        # Save the output
        if data is not None:
            try:
                logger.info("Saving data to output file...")
                output_path = await save_output(data, output_file)
                logger.info("Data successfully saved to: %s", output_path)

                # Verify the file was created and has content
                if output_path.exists():
                    file_size = output_path.stat().st_size
                    logger.debug("Output file size: %d bytes", file_size)
                    if file_size == 0:
                        logger.warning("Output file is empty")
                    click.echo(f"Data successfully saved to: {output_path}")
                else:
                    logger.error("Output file was not created")
                    raise click.FileError("Failed to create output file") from None

            except Exception as e:
                logger.error("Error saving output: %s", str(e), exc_info=debug)
                raise click.FileError(f"Failed to save output: {e}") from e
        else:
            logger.warning("No data to save")
            raise click.UsageError("No data was returned from the provider")

        return 0

    except click.ClickException:
        raise  # Re-raise Click exceptions as-is
    except Exception as e:
        logger.error("Unexpected error: %s", str(e), exc_info=debug)
        raise click.ClickException(f"Unexpected error: {str(e)}")
    finally:
        # Clean up resources
        if 'provider' in locals():
            try:
                if hasattr(provider, 'close'):
                    logger.debug("Closing provider...")
                    await provider.close()
            except Exception as e:
                logger.warning("Error closing provider: %s", e, exc_info=debug)
                click.echo(f"Warning: Error closing provider: {e}", err=True)


def register_provider_commands(cli):
    """Register provider commands with the main CLI."""
    cli.add_command(provider_cli)
