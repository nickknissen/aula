# Aula

[![PyPI](https://img.shields.io/pypi/v/aula)](https://pypi.org/project/aula/)
[![Python](https://img.shields.io/pypi/pyversions/aula)](https://pypi.org/project/aula/)
[![License](https://img.shields.io/pypi/l/aula)](LICENSE)

Async Python client for the Danish school platform **aula.dk**.

- Fetch calendar events, messages, posts, and daily overviews
- Authenticate via Denmark's MitID national identity system
- Token caching — MitID app approval only needed on first login
- Full async API client (`AulaApiClient`) and a CLI included

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Authentication](#authentication)
- [CLI](#cli)
- [AI Agent Integration](#ai-agent-integration)
- [Attribution](#attribution)
- [License](#license)

## Installation

```bash
pip install aula
# or with uv
uv add aula
```

**Requirements:** Python >= 3.10, MitID username and MitID app.

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

Key methods on `AulaApiClient`: `get_profile()`, `get_daily_overview(child_id)`, `get_message_threads()`, `get_messages_for_thread(thread_id)`, `get_calendar_events(...)`, `get_posts(...)`. See `src/aula/api_client.py` for the full list.

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

```bash
aula --username <your_mitid_username> [COMMAND]
```

The username can also be set via the `AULA_MITID_USERNAME` environment variable or a config file (`~/.config/aula/config.json`).

| Command | Description |
|---|---|
| `login` | Verify credentials |
| `profile` | Show profile and children |
| `overview` | Daily overview for all children |
| `messages` | Recent message threads |
| `calendar` | Calendar events |
| `posts` | Posts and announcements |
| `notifications` | Recent notifications |
| `daily-summary` | Today's schedule, homework & messages |
| `weekly-summary` | Full week overview with provider data |
| `presence-templates` | Planned entry/exit times |
| `mu:opgaver` | Min Uddannelse tasks |
| `mu:ugeplan` | Min Uddannelse weekly letter |
| `easyiq:ugeplan` | EasyIQ weekly plan |
| `easyiq:homework` | EasyIQ homework |
| `meebook:ugeplan` | Meebook weekly plan |
| `momo:forløb` | MoMo courses |
| `momo:huskeliste` | MoMo reminders |
| `library:status` | Library loans & reservations |
| `widgets` | List available widgets |
| `download-images` | Download images from gallery/posts/messages |
| `agent-setup` | Install AI agent skill (see below) |

Example:

```bash
aula --username johndoe messages --limit 5
# or without installing
uvx aula --username johndoe messages --limit 5
```

### JSON output

All commands support `--output json` for machine-readable output:

```bash
aula --output json messages --unread
aula --output json daily-summary --child "Emma"
aula --output json calendar --start-date 2026-03-10
```

Set the `AULA_OUTPUT=json` environment variable to make JSON the default.

## AI Agent Integration

The CLI is designed to work with AI coding agents like [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and [OpenCode](https://opencode.ai). The `agent-setup` command installs a skill that teaches agents how to query Aula for school data.

```bash
# Install for the current project
aula agent-setup

# Install globally (all projects)
aula agent-setup --global
```

This creates a `SKILL.md` following the [Agent Skills](https://agentskills.io) open standard under `.claude/skills/aula/`, which is read by both Claude Code and OpenCode. Once installed, agents can invoke `/aula` or automatically use the CLI when you ask about school data.

## Attribution

- Aula API usage was inspired by the [scaarup/aula](https://github.com/scaarup/aula) Home Assistant integration.
- MitID authentication was inspired by the [Hundter/MitID-BrowserClient](https://github.com/Hundter/MitID-BrowserClient) project.
- EasyIQ widget integration (weekplan and homework) was inspired by the [esbenwiberg/easyiq](https://github.com/esbenwiberg/easyiq) Home Assistant integration.

## License

MIT
