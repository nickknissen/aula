# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Aula is a Python async library and CLI for the Danish school platform **aula.dk**. It provides an async API client (`AulaApiClient`) and a Click-based CLI for fetching profiles, daily overviews, messages, calendar events, posts, and widget data. Authentication uses Denmark's MitID national identity system via a headless OAuth 2.0 + SAML + MitID flow.

## Commands

```bash
# Sync dependencies (uses uv as package manager)
uv sync

# Run CLI
aula --username <mitid_username> <command>
# or: python -m aula

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Run tests
pytest
```

## Release Flow

1. Bump `version` in `pyproject.toml` (semver: patch for fixes/docs, minor for new features)
2. Commit: `git commit -m "chore: bump version to X.Y.Z"`
3. Push: `git push`
4. Create a GitHub release — this triggers the PyPI publish workflow (`.github/workflows/publish.yml`):
   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z" --notes "- change 1\n- change 2"
   ```
5. Verify the Actions run at https://github.com/nickknissen/aula/actions and the new version appears on PyPI.

When working with Python, invoke the relevant /astral:\<skill> for uv, ty, and ruff to ensure best practices are followed.

## Ruff Configuration

- Target: Python 3.10 (`py310`)
- Line length: 100
- Rules: `E`, `F`, `W`, `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM` (simplify), `LOG` (logging)

## Architecture

### Project Layout

```
pyproject.toml              # single package: name = "aula"
src/aula/
  __init__.py
  __main__.py               # python -m aula entry point
  api_client.py             # async API client
  auth_flow.py              # high-level auth orchestration
  cli.py                    # Click CLI commands
  config.py                 # CLI config (~/.config/aula/config.json)
  const.py                  # API base URLs, user agent
  http.py                   # HTTP abstraction protocol
  http_httpx.py             # httpx implementation
  token_storage.py          # token persistence (ABC + file impl)
  auth/                     # MitID authentication
    mitid_client.py, browser_client.py, srp.py, exceptions.py, _utils.py
  models/                   # API data models (one file per model)
    base.py, child.py, message.py, post.py, calendar_event.py, ...
  utils/
    html.py                 # HTML-to-text helpers
    table.py                # calendar table rendering (rich or plain)
    download.py             # image download orchestration
tests/                      # mirrors src/aula/ structure
```

### Module Dependency Flow

```
cli.py → api_client.py → auth/mitid_client.py → auth/browser_client.py → auth/srp.py
  │            │
  │            ├→ models/ → utils/html.py
  │            ├→ const.py
  │            └→ token_storage.py
  ├→ config.py
  └→ utils/{table.py, download.py}
```

### Key Modules

- **`api_client.py`** — `AulaApiClient`: async context manager wrapping `httpx.AsyncClient`. Handles login, API version auto-retry (bumps version on 410 Gone, up to 5 retries), and all endpoint methods.
- **`auth/mitid_client.py`** — `MitIDAuthClient`: 7-step auth flow (OAuth+PKCE → SAML broker → MitID app auth → SAML back → token exchange).
- **`auth/browser_client.py`** — `BrowserClient`: low-level MitID protocol (QR codes, OTP, SRP handshake).
- **`auth/srp.py`** — `CustomSRP`: Secure Remote Password protocol with AES-GCM via cryptography.
- **`models/`** — Dataclasses inheriting `AulaDataClass` (one file per model). Every model carries an optional `_raw: dict` preserving original API response. Uses `from_dict()` classmethods for parsing.
- **`token_storage.py`** — `TokenStorage` ABC with `load()`/`save()` async methods; `FileTokenStorage` is the JSON file implementation.
- **`cli.py`** — Click command group. Uses `@async_cmd` decorator to bridge sync Click to async via `asyncio.run()`. Sets `WindowsSelectorEventLoopPolicy` on Windows.
- **`config.py`** — CLI config at `~/.config/aula/config.json`.
- **`const.py`** — API base URLs (current base version: v22) and user agent.
- **`utils/table.py`** — Calendar table rendering (rich or plain text fallback).
- **`utils/download.py`** — Image download orchestration for gallery, posts, messages.

### Key Patterns

- **Async-first**: all API and auth code is async (`httpx.AsyncClient`).
- **Convention commits**: `feat:`, `refactor:`, `chore:`, `fix:`.
- **`_raw` field**: models preserve original API dicts for debugging/extensibility.
- **Defensive parsing**: `try/except` around response parsing with `logging.warning` on failures.
- **Optional rich dependency**: calendar table rendering falls back to plain text if `rich` is not installed.
- **MitID username resolution order** (CLI): `--username` flag → `AULA_MITID_USERNAME` env var → config file → interactive prompt.
