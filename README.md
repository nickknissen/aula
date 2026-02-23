# Aula

[![PyPI](https://img.shields.io/pypi/v/aula)](https://pypi.org/project/aula/)
[![Python](https://img.shields.io/pypi/pyversions/aula)](https://pypi.org/project/aula/)
[![License](https://img.shields.io/pypi/l/aula)](LICENSE)

Async Python client for the Danish school platform **aula.dk**.

- Fetch calendar events, messages, posts, and daily overviews
- Authenticate via Denmark's MitID national identity system
- Token caching — MitID app approval only needed on first login
- Full async API client (`AulaApiClient`) and a CLI included

## Installation

```bash
pip install aula
```

**Requirements:** Python >= 3.10, MitID username and MitID app.

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

## Authentication

### What You Need

- **MitID username** — your MitID username (not your Aula username). Find it at [mitid.dk](https://mitid.dk/).
- **MitID app** — installed and set up on your phone.

### First Login

On first run you'll be prompted to approve the login in your MitID app. You may need to scan a QR code or enter an OTP shown in the terminal. Tokens are saved to the storage file and reused on subsequent runs — no app interaction needed until they expire.

### Token Security

Tokens provide full access to your Aula account — treat them like passwords and never commit token files to version control.

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

Example:

```bash
aula --username johndoe messages --limit 5
```

## License

MIT
