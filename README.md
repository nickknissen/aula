# Aula

[![PyPI](https://img.shields.io/pypi/v/aula)](https://pypi.org/project/aula/)
[![Python](https://img.shields.io/pypi/pyversions/aula)](https://pypi.org/project/aula/)
[![License](https://img.shields.io/pypi/l/aula)](LICENSE)

Unofficial async Python client for the Danish school platform **aula.dk**. The project delivers:

1. **Async Python API client** — programmatic access to profiles, messages, calendar, posts, and more
2. **CLI** — read messages, calendar, posts, presence, and widget data from the terminal
3. **AI agent skill** — teach [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or [OpenCode](https://opencode.ai) to query school data

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Authentication](#authentication)
- [CLI](#cli)
- [Configuration](#configuration)
- [AI Agent Integration](#ai-agent-integration)
- [Project Structure](#project-structure)
- [Attribution](#attribution)
- [License](#license)

## Installation

```bash
pip install aula
# or with uv
uv add aula
```

**Requirements:** Python >= 3.14, MitID username and MitID app.

### Run without installing

Use `uvx` to run the CLI directly from PyPI without a permanent install:

```bash
uvx aula --username johndoe messages --limit 5
```

### Install from Source

```bash
git clone https://github.com/nickknissen/aula.git
cd aula
pip install -e .
```

## Quick Start

```python
import asyncio
from aula import FileTokenStorage
from aula.auth_flow import authenticate_and_create_client

async def main():
    token_storage = FileTokenStorage(".aula_tokens.json")
    async with await authenticate_and_create_client("your_mitid_username", token_storage) as client:
        profile = await client.get_profile()
        print(profile.display_name)
        for child in profile.children:
            overview = await client.get_daily_overview(child.id)

asyncio.run(main())
```

Key methods on `AulaApiClient`: `get_profile()`, `get_daily_overview(child_id)`, `get_message_threads()`, `get_messages_for_thread(thread_id)`, `get_calendar_events(...)`, `get_posts(...)`, `get_groups(...)`, `get_message_folders(...)`, `search(...)`, `update_presence_template(...)`. See `src/aula/api_client.py` for the full list.

### Widget API (Namespace)

Widget integrations are available via the namespaced widgets client on `AulaApiClient`:

```python
tasks = await client.widgets.get_mu_tasks(
    widget_id="0030",  # WIDGET_MIN_UDDANNELSE_TASKS
    child_filter=["12345"],
    institution_filter=["5678"],
    week="2026-W8",
    session_uuid="guardian-user-id",
)
```

Use the `client.widgets.*` namespace for widget calls (for example: `get_mu_tasks`, `get_ugeplan`, `get_easyiq_weekplan`, `get_meebook_weekplan`, `get_momo_courses`, `get_library_status`).

Legacy direct widget methods on `AulaApiClient` are deprecated and will be removed in a future release. Migrate to `client.widgets.<method>(...)`.

## Authentication

### What You Need

- **MitID username** — your MitID username (not your Aula username). Find it at [mitid.dk](https://mitid.dk/).
- **MitID app** — installed and set up on your phone.

### First Login

On first run you'll be prompted to approve the login in your MitID app. You may need to scan a QR code or enter an OTP shown in the terminal. Tokens are saved to the storage file and reused on subsequent runs — no app interaction needed until they expire.

### Token Security

Tokens provide full access to your Aula account — treat them like passwords and never commit token files to version control.

### How It Works

For a detailed breakdown of the authentication flow (OAuth + SAML + MitID), session cookies, and how this library differs from the browser login, see [docs/aula-authentication.md](docs/aula-authentication.md).

## CLI

Install as a standalone tool:

```bash
# with uv (recommended)
uv tool install aula

# or with pip
pip install aula
```

Then run:

```bash
aula --username <your_mitid_username> [COMMAND]
```

The username can also be set via the `AULA_MITID_USERNAME` environment variable or a [config file](#configuration).

### Core

| Command | Description |
|---|---|
| `aula login` | Verify credentials |
| `aula profile` | Show profile and children |
| `aula overview` | Daily overview for all children |
| `aula daily-summary` | Today's schedule, homework & messages |
| `aula weekly-summary` | Full week overview with provider data |

### Messages

| Command | Description |
|---|---|
| `aula messages` | Recent message threads |
| `aula contacts` | Contact list |
| `aula notifications` | Recent notifications |
| `aula search` | Search documents across Aula |

### Calendar

| Command | Description |
|---|---|
| `aula calendar` | Calendar events |
| `aula important-dates` | Important dates |
| `aula birthdays` | Birthday events |

### Presence

| Command | Description |
|---|---|
| `aula presence` | Presence registrations and states |
| `aula presence-templates` | Planned entry/exit times |
| `aula update-presence` | Update pickup/drop-off times |

### Content

| Command | Description |
|---|---|
| `aula posts` | Posts and announcements |
| `aula groups` | Groups and group members |
| `aula download-images` | Download images from gallery/posts/messages |

### Widgets

| Command | Description |
|---|---|
| `aula widgets` | List available widgets |
| `aula mu:opgaver` | Min Uddannelse tasks |
| `aula mu:ugeplan` | Min Uddannelse weekly letter |
| `aula easyiq:ugeplan` | EasyIQ weekly plan |
| `aula easyiq:homework` | EasyIQ homework |
| `aula meebook:ugeplan` | Meebook weekly plan |
| `aula momo:forløb` | MoMo courses |
| `aula momo:huskeliste` | MoMo reminders |
| `aula library:status` | Library loans & reservations |

### Global flags

| Flag | Description |
|---|---|
| `--username` | MitID username (or `AULA_MITID_USERNAME` env var) |
| `--output text\|json` | Output format (or `AULA_OUTPUT` env var) |
| `--auth-method app\|token` | MitID auth method (or `AULA_AUTH_METHOD` env var) |
| `-v` / `-vv` / `-vvv` | Increase verbosity (warning / info / debug) |

### JSON output

All commands support `--output json` for machine-readable output:

```bash
aula --output json messages --unread
aula --output json daily-summary --child "Emma"
aula --output json calendar --start-date 2026-03-10
```

### Examples

```bash
aula --username johndoe messages --limit 5
# or without installing
uvx aula --username johndoe messages --limit 5
```

## Configuration

`~/.config/aula/config.json`:

```json
{
  "mitid_username": "your_mitid_username"
}
```

The username is saved automatically on first login. CLI flags and environment variables take precedence over the config file.

## AI Agent Integration

The CLI is designed to work with AI coding agents like [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and [OpenCode](https://opencode.ai). The `agent-setup` command installs a skill that teaches agents how to query Aula for school data.

```bash
# Install for the current project
aula agent-setup

# Install globally (all projects)
aula agent-setup --global
```

This creates a `SKILL.md` following the [Agent Skills](https://agentskills.io) open standard under `.claude/skills/aula/`, which is read by both Claude Code and OpenCode. Once installed, agents can invoke `/aula` or automatically use the CLI when you ask about school data.

## Project Structure

```
src/aula/
  api_client.py             # Async API client (main entry point)
  cli.py                    # Click CLI commands
  auth_flow.py              # High-level auth orchestration
  config.py                 # CLI config (~/.config/aula/config.json)
  token_storage.py          # Token persistence (ABC + file impl)
  auth/                     # MitID authentication
    mitid_client.py         # 7-step OAuth+SAML+MitID flow
    browser_client.py       # Low-level MitID protocol (QR, OTP, SRP)
    srp.py                  # Secure Remote Password with AES-GCM
  models/                   # API data models (one file per model)
  utils/                    # HTML helpers, table rendering, downloads
tests/                      # Mirrors src/aula/ structure
```

## Attribution

- Aula API usage was inspired by the [scaarup/aula](https://github.com/scaarup/aula) Home Assistant integration.
- MitID authentication was inspired by the [Hundter/MitID-BrowserClient](https://github.com/Hundter/MitID-BrowserClient) project.
- EasyIQ widget integration (weekplan and homework) was inspired by the [esbenwiberg/easyiq](https://github.com/esbenwiberg/easyiq) Home Assistant integration.

## License

MIT
