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
ruff check src/
ruff format src/

# No test suite exists yet
```

When working with Python, invoke the relevant /astral:\<skill> for uv, ty, and ruff to ensure best practices are followed.

## Ruff Configuration

- Target: Python 3.10 (`py310`)
- Line length: 100
- Rules: `E`, `F`, `W`, `I` (isort), `UP` (pyupgrade)

## Architecture

### Module Dependency Flow

```
cli.py → api_client.py → auth/mitid_client.py → auth/browser_client.py → auth/srp.py
  │            │
  │            ├→ models.py → utils/html.py
  │            ├→ const.py
  │            └→ token_storage.py
  ├→ config.py
  └→ utils/table.py
```

### Key Modules

- **`api_client.py`** — `AulaApiClient`: async context manager wrapping `httpx.AsyncClient`. Handles login, API version auto-retry (bumps version on 410 Gone, up to 5 retries), and all endpoint methods.
- **`auth/mitid_client.py`** — `MitIDAuthClient`: 7-step auth flow (OAuth+PKCE → SAML broker → MitID app auth → SAML back → token exchange).
- **`auth/browser_client.py`** — `BrowserClient`: low-level MitID protocol (QR codes, OTP, SRP handshake).
- **`auth/srp.py`** — `CustomSRP`: Secure Remote Password protocol with AES-GCM via pycryptodome.
- **`models.py`** — Dataclasses inheriting `AulaDataClass`. Every model carries an optional `_raw: dict` preserving original API response. Uses `from_dict()` classmethods for parsing.
- **`token_storage.py`** — `TokenStorage` ABC with `load()`/`save()` async methods; `FileTokenStorage` is the JSON file implementation.
- **`cli.py`** — Click command group. Uses `@async_cmd` decorator to bridge sync Click to async via `asyncio.run()`. Sets `WindowsSelectorEventLoopPolicy` on Windows.
- **`config.py`** — CLI config at `~/.config/aula/config.json`.
- **`const.py`** — API base URLs (current base version: v21) and user agent.

### Key Patterns

- **Async-first**: all API and auth code is async (`httpx.AsyncClient`).
- **Convention commits**: `feat:`, `refactor:`, `chore:`, `fix:`.
- **`_raw` field**: models preserve original API dicts for debugging/extensibility.
- **Defensive parsing**: `try/except` around response parsing with `logging.warning` on failures.
- **Optional rich dependency**: calendar table rendering falls back to plain text if `rich` is not installed.
- **MitID username resolution order** (CLI): `--username` flag → `AULA_MITID_USERNAME` env var → config file → interactive prompt.
