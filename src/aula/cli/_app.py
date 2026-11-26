import asyncio
import functools
import logging
import os
import platform
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import click

from .. import __version__
from ..api_client import AulaApiClient
from ..auth_flow import authenticate_and_create_client
from ..config import CONFIG_FILE, DEFAULT_TOKEN_FILE, load_config, save_config
from ..http import AulaRefreshTokenConflictError
from ..token_storage import FileTokenStorage
from ..utils.diagnostics import credential_logger
from ..utils.output import (
    echo,
)
from ..utils.qr import TerminalQRDisplay

_LOGGER = credential_logger(__name__)


# Decorator to run async functions within Click commands
def async_cmd(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # On Windows, use SelectorEventLoop to avoid 'Event loop closed' issues
        loop_factory = asyncio.SelectorEventLoop if sys.platform.startswith("win") else None
        return asyncio.run(func(*args, **kwargs), loop_factory=loop_factory)

    return wrapper


def get_mitid_username(ctx: click.Context) -> str:
    """Get MitID username from context, environment, config, or prompt."""
    # First try context (command line)
    username = ctx.obj.get("MITID_USERNAME")

    # Then try environment variable
    if not username:
        username = os.getenv("AULA_MITID_USERNAME")

    # Then try config file
    if not username:
        config = load_config()
        username = config.get("mitid_username")

    # Finally, prompt if still missing
    if not username:
        echo("MitID authentication required")
        username = click.prompt("MitID username")

        if click.confirm("Save MitID username to config file?"):
            config = load_config()
            config["mitid_username"] = username
            save_config(config)
            echo(f"Username saved to {CONFIG_FILE}")

    return username


class _TokenFileConflict(BaseException):
    """A refresh token conflict met while a command runs."""


def _stop_command_on_token_conflict(client: AulaApiClient) -> None:
    refresh = client._on_token_refresh
    if refresh is None:
        return

    async def refresh_or_stop() -> str | None:
        try:
            return await refresh()
        except AulaRefreshTokenConflictError as conflict:
            raise _TokenFileConflict from conflict

    client._on_token_refresh = refresh_or_stop


class _AulaGroup(click.Group):
    """Command group that stops with a short message when the token file is shared."""

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except AulaRefreshTokenConflictError, _TokenFileConflict:
            raise click.ClickException(
                f"another process is using the token file {_token_file(ctx)}. "
                "Stop it, or give the second process its own file with --token-file."
            ) from None


@click.group(cls=_AulaGroup)
@click.version_option(
    __version__,
    "--version",
    prog_name="aula",
    # Bug reports arrive as tracebacks, and both numbers are needed to read one.
    message=f"%(prog)s %(version)s (Python {platform.python_version()})",
)
@click.option(
    "--username",
    help="MitID username (can also be set via AULA_MITID_USERNAME env var or config file)",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity: -v for INFO, -vv for DEBUG.",
)
@click.option(
    "--auth-method",
    type=click.Choice(["app", "token"], case_sensitive=False),
    default="app",
    envvar="AULA_AUTH_METHOD",
    help="MitID auth method: 'app' (QR/OTP) or 'token' (code token + password).",
)
@click.option(
    "--password",
    envvar="AULA_MITID_PASSWORD",
    help="MitID password for --auth-method token (or AULA_MITID_PASSWORD env var). "
    "Prompted for when omitted.",
)
@click.option(
    "--token-code",
    envvar="AULA_MITID_TOKEN_CODE",
    help="6 digits from your MitID kodeviser (or AULA_MITID_TOKEN_CODE env var). "
    "Prompted for when omitted; the code rotates, so this is only useful per-run.",
)
@click.option(
    "--output",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    envvar="AULA_OUTPUT",
    help="Output format: 'text' (human-readable) or 'json' (machine-readable).",
)
@click.option(
    "--token-file",
    type=click.Path(dir_okay=False, path_type=Path),
    envvar="AULA_TOKEN_FILE",
    help=f"Where the session is saved (or AULA_TOKEN_FILE env var). Default: {DEFAULT_TOKEN_FILE}",
)
@click.option(
    "--identity",
    type=click.IntRange(min=1),
    envvar="AULA_MITID_IDENTITY",
    help="Which MitID identity to log in as when there are several, 1 being the first "
    "(or AULA_MITID_IDENTITY env var). Asked for when omitted.",
)
@click.pass_context
def cli(
    ctx,
    username: str | None,
    verbose: int,
    auth_method: str,
    password: str | None,
    token_code: str | None,
    output_format: str,
    token_file: Path | None,
    identity: int | None,
):
    """CLI for interacting with Aula API"""
    # Configure logging based on verbosity
    log_level = logging.ERROR  # Default: errors only (no warnings in normal output)
    if verbose == 1:
        log_level = logging.WARNING  # -v: Show warnings and above
    elif verbose == 2:
        log_level = logging.INFO  # -vv: Show info and above
    elif verbose >= 3:
        log_level = logging.DEBUG  # -vvv: Show debug and above

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
        force=True,  # Ensures reconfiguration even if root handlers exist
    )

    # Set library loggers to a less verbose level to reduce noise
    if log_level < logging.WARNING:
        for lib_name in ["httpx", "httpcore", "asyncio"]:
            logging.getLogger(lib_name).setLevel(logging.WARNING)

    # Initialize context
    ctx.ensure_object(dict)

    ctx.obj["AUTH_METHOD"] = auth_method
    ctx.obj["OUTPUT_FORMAT"] = output_format
    ctx.obj["MITID_PASSWORD"] = password
    ctx.obj["MITID_TOKEN_CODE"] = token_code
    ctx.obj["TOKEN_FILE"] = token_file
    ctx.obj["MITID_IDENTITY"] = identity

    if username:
        ctx.obj["MITID_USERNAME"] = username


def _on_login_required():
    """Notify the user that MitID authentication is needed."""
    echo("Session expired or not found. Please open your MitID app to approve the login.")


async def _prompt_for_identity(identities: list[str]) -> int:
    """Ask which of several MitID identities to log in as, 1 being the first."""
    echo("\nMultiple identities found. Please select one:")
    for i, identity in enumerate(identities, 1):
        echo(f"  {i}. {identity}")
    return click.prompt("Select identity", type=click.IntRange(1, len(identities)), default=1)


class _MitIDLogin:
    """The CLI's side of one login: answers MitID's questions and notes what happened."""

    def __init__(self, requested_identity: int | None) -> None:
        self.requested_identity = requested_identity
        self.identity: int | None = None
        self.ran = False

    def started(self) -> None:
        self.ran = True
        _on_login_required()

    async def choose_identity(self, identities: list[str]) -> int:
        number = self.requested_identity or await _prompt_for_identity(identities)
        if number > len(identities):
            raise click.BadParameter(
                f"{number} is out of range, there are {len(identities)} MitID identities.",
                param_hint="'--identity'",
            )
        self.identity = number
        return number - 1

    def warn_if_identity_went_unused(self) -> None:
        if self.ran and self.identity is None and (self.requested_identity or 1) > 1:
            echo(
                f"Warning: --identity {self.requested_identity} was ignored, "
                "because MitID offered only one identity.",
                err=True,
            )


def _print_otp_code(code: str) -> None:
    """Show the code the user types into the MitID app in place of scanning."""
    echo("=" * 60)
    echo(f"ENTER THIS CODE IN YOUR MITID APP: {code}")
    echo("=" * 60)


def _token_digits_provider(ctx: click.Context) -> Callable[[], Awaitable[str]]:
    """Supply the kodeviser digits from the CLI/env, falling back to a prompt."""

    async def provide() -> str:
        supplied = ctx.obj.get("MITID_TOKEN_CODE")
        if supplied:
            return supplied
        return click.prompt("MitID token code (6 digits)", type=str)

    return provide


def _password_provider(ctx: click.Context) -> Callable[[], Awaitable[str]]:
    """Supply the MitID password from the CLI/env, falling back to a prompt."""

    async def provide() -> str:
        supplied = ctx.obj.get("MITID_PASSWORD")
        if supplied:
            return supplied
        return click.prompt("MitID password", hide_input=True, type=str)

    return provide


def _token_file(ctx: click.Context) -> Path:
    return ctx.obj.get("TOKEN_FILE") or DEFAULT_TOKEN_FILE


async def _log_in(
    ctx: click.Context, *, force_login: bool = False
) -> tuple[AulaApiClient, int | None]:
    """Log in, returning the client and the MitID identity chosen, if MitID asked."""
    username = get_mitid_username(ctx)
    token_storage = FileTokenStorage(_token_file(ctx))
    mitid = _MitIDLogin(ctx.obj.get("MITID_IDENTITY"))
    qr_display = TerminalQRDisplay()
    try:
        client = await authenticate_and_create_client(
            username,
            token_storage,
            on_qr_codes=qr_display.show,
            on_qr_done=qr_display.done,
            on_otp_code=_print_otp_code,
            on_login_required=mitid.started,
            on_identity_selected=mitid.choose_identity,
            auth_method=ctx.obj.get("AUTH_METHOD", "app"),
            on_token_digits=_token_digits_provider(ctx),
            on_password=_password_provider(ctx),
            force_login=force_login,
        )
    finally:
        qr_display.stop()
    mitid.warn_if_identity_went_unused()
    _stop_command_on_token_conflict(client)
    return client, mitid.identity


async def _get_client(ctx: click.Context) -> AulaApiClient:
    """Create an authenticated AulaApiClient."""
    client, _ = await _log_in(ctx)
    return client
