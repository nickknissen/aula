---
name: aula-widget-provider
description: >
  Accelerate adding new Aula widget provider integrations (ugeplan, tasks, etc.) to the
  aula.dk Python CLI project. Use when the user asks to add a new third-party widget
  provider command such as "add meebook:ugeplan", "implement provider:tasks", "add a new
  widget integration", or similar requests to connect a new Aula widget API. Covers the
  full 5-file change pattern: constants, models, model exports, API client method, and CLI command.
---

# Aula Widget Provider Integration

## Workflow

Adding a new widget provider always touches 5 files in the same order:

1. **`src/aula/const.py`** -- Add `<PROVIDER>_API` base URL and `WIDGET_<PROVIDER>` ID
2. **`src/aula/models/<provider>_<type>.py`** -- Create dataclass models with `from_dict()` + `_raw`
3. **`src/aula/models/__init__.py`** -- Export the top-level model
4. **`src/aula/api_client.py`** -- Add async method: get bearer token, build params/headers, request, parse
5. **`src/aula/cli.py`** -- Add Click command with standard boilerplate (profile, filters, session UUID, call, display)

## Before Starting

Gather from the user or reverse-engineer from the widget source:
- API base URL
- Widget ID (4-digit string)
- HTTP method (GET or POST) and endpoint path
- Required headers beyond `Authorization: Bearer` and `Accept: application/json`
- Query params / request body structure
- Response JSON shape (bare array vs nested under `data`)

## Code Templates

Read [references/code-patterns.md](references/code-patterns.md) for complete code templates for each file.

## Key Conventions

- All models inherit `AulaDataClass` from `models/base.py`
- Every model has `_raw: dict | None = field(default=None, repr=False)`
- CLI commands use colon naming: `"provider:command"`
- Week resolved via `_resolve_week()` (handles `None`, bare number, `YYYY-Wn`)
- HTML content stripped via `utils.html.html_to_plain()`
- Run `ruff check src/` and `ruff format src/` after changes
