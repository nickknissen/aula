# Aula: Python Aula API Client Library

Python library for interacting with the Aula platform using the **new MitID authentication system**.

This library provides an asynchronous client (`AulaApiClient`) to fetch data such as profiles, daily overviews, messages, and calendar events from Aula.

## 🚨 Important: MitID Authentication Required

**Aula has migrated from UniLogin to MitID authentication.** This library now uses the new MitID system.

- ✅ Requires **MitID username** and **MitID app** for authentication
- ✅ Token caching for fast subsequent logins
- ✅ Headless operation (no browser needed)
- ❌ Old username/password authentication **no longer works**

**If you're upgrading from an older version**, see [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) for detailed migration instructions.

## TODO:
### Core functionality
✅ Calendar fetching
✅ Post fetching
✅ Messages fetching
✅ Daily Overview fetching
✅ Profile fetching
### Widgets:
📋 0001 - EasyIQ - Ugeplan
📋 0004 - Meebook Ugeplan
📋 0019 - Biblioteket
📋 0029 - MinUddannelse Ugenoter
📋 0030 - MinUddannelse Opgaver
📋 0047 - Fravær - forældreindberetning
📋 0062 - Huskelisten
📋 0121 - INFOBA Modulordninger til forældre


## Library Usage

Here's a basic example of how to use the `AulaApiClient` with MitID authentication:

```python
import asyncio
from aula import AulaApiClient, FileTokenStorage

async def main():
    # Replace with your MitID username
    # NOTE: This is your MitID username, NOT your Aula username!
    mitid_username = "your_mitid_username"

    # Create a token storage backend (persists tokens to a file)
    token_storage = FileTokenStorage(".aula_tokens.json")

    # Create the client with async context manager for proper cleanup
    async with AulaApiClient(
        mitid_username=mitid_username,
        token_storage=token_storage,
        debug=False  # Set to True for detailed logs
    ) as client:
        # Login using MitID
        # First time: Will prompt you to approve in MitID app
        # Subsequent times: Uses cached tokens (fast!)
        print("Logging in with MitID...")
        print("Please approve the login in your MitID app if prompted")
        await client.login()
        print(f"Successfully logged in! API URL: {client.api_url}")

        # Fetch profile information
        profile = await client.get_profile()
        print(f"User: {profile.display_name} (ID: {profile.profile_id})")

        if profile.children:
            print("Children:")
            for child in profile.children:
                print(f" - {child.name} (ID: {child.id})")

                # Fetch daily overview for the first child
                if child == profile.children[0]:
                    overview = await client.get_daily_overview(child.id)
                    if overview:
                        print(f"   Overview for {child.name}:")
                        print(f"   - Status: {overview.status}")
        else:
            print("No children found.")

if __name__ == "__main__":
    asyncio.run(main())
```

### First Login Experience

When you run the code for the first time:
1. You'll see a message: "Please approve the login in your MitID app"
2. Open your **MitID app** on your phone
3. You may need to scan a QR code or enter an OTP code (shown in terminal)
4. Approve the login request
5. Tokens are saved and cached for future use

On subsequent runs, tokens are loaded from cache - no MitID app interaction needed!

### Available Methods

Key methods of `AulaApiClient` include:

- `login()`: Authenticate and initialize the session.
- `is_logged_in()`: Check if the session is currently active.
- `get_profile()`: Fetch user and child profile information.
- `get_daily_overview(child_id)`: Fetch the daily overview for a specific child.
- `get_message_threads()`: Fetch message threads.
- `get_messages_for_thread(thread_id)`: Fetch messages within a specific thread.
- `get_calendar_events(...)`: Fetch calendar events.
- `get_posts(...)`: Fetch posts/announcements.
- _... (and others, see `api_client.py` for details)_

### Data Models

The library uses dataclasses to structure the returned data (e.g., `Profile`, `Child`, `DailyOverview`, `MessageThread`). Check `models.py` for the specific fields available in each model.

## Authentication Requirements

### What You Need
1. **MitID Username**: Your MitID username (NOT your Aula username)
   - Find it by logging into https://mitid.dk/
   - Usually in format: "FirstnameLastname" or similar

2. **MitID App**: The MitID mobile app installed on your phone
   - Available on iOS and Android
   - Must be set up and working

### How Authentication Works
1. **First Login**: Complete OAuth + SAML + MitID flow (requires app approval)
2. **Token Caching**: Access tokens are saved to a local file
3. **Subsequent Logins**: Tokens are reused (no app interaction needed)
4. **Token Expiration**: When tokens expire, re-authenticate with app

### Token Security
- Tokens provide full access to your Aula account
- Store token files securely
- Add to `.gitignore`:
  ```gitignore
  .aula_tokens.json
  ```

## Installation

### Requirements
- Python >= 3.10
- MitID username and MitID app

### Install from PyPI
```bash
pip install aula
```

### Install from Source
```bash
git clone https://github.com/yourusername/aula.git
cd aula
pip install -e .
```

### Dependencies
The library automatically installs:
- `httpx` - Async HTTP client
- `beautifulsoup4` - HTML parsing
- `qrcode` - QR code generation for MitID
- `pycryptodome` - Cryptography for MitID protocol
- Other required dependencies

## CLI Tool

A command-line interface is included for quick access to Aula data. It uses MitID authentication.

```bash
# General command structure (username can also be set via AULA_MITID_USERNAME env var)
aula --username <your_mitid_username> [COMMAND] [OPTIONS]
```

### CLI Commands

**1. Login:**
Verifies credentials by authenticating with MitID.

```bash
aula --username <your_mitid_username> login
```

**2. Profile:**
Fetches and displays profile information.

```bash
aula --username <your_mitid_username> profile
```

**3. Overview:**
Fetches the daily overview. By default, it fetches for all children. Specify a single child with `--child-id`.

```bash
# Get overview for all children
aula --username <your_mitid_username> overview

# Get overview for a specific child
aula --username <your_mitid_username> overview --child-id 12345
```

**4. Messages:**
Fetches recent message threads and their contents.

```bash
aula --username <your_mitid_username> messages --limit 5
```

**5. Calendar:**
Fetches calendar events for the next 7 days (default).

```bash
aula --username <your_mitid_username> calendar --start-date 2025-01-01 --end-date 2025-01-07
```

**6. Posts:**
Fetches posts and announcements.

```bash
aula --username <your_mitid_username> posts --limit 10
```
