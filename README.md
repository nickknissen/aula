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
from aula import AulaApiClient

async def main():
    # Replace with your MitID username
    # NOTE: This is your MitID username, NOT your Aula username!
    mitid_username = "your_mitid_username"

    # Create the client
    client = AulaApiClient(
        mitid_username=mitid_username,
        token_file=".aula_tokens.json",  # Optional: token cache location
        debug=False  # Set to True for detailed logs
    )

    try:
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
                    print(f"   Overview for {child.name}:")
                    print(f"   - Status: {overview.status_text}")
        else:
            print("No children found.")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Close HTTP clients (important!)
        await client.close()

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
- _... (and others, see `api_client.py` for details)_

### Data Models

The library uses dataclasses to structure the returned data (e.g., `Profile`, `Child`, `DailyOverview`, `MessageThread`). Check `api_client.py` for the specific fields available in each model.

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

## CLI Tool (Example Usage)

A simple command-line interface (CLI) is included as a demonstration of how to use the library.

**Note:** This CLI requires your Aula username and password for authentication, provided as options for every command.

```bash
# General command structure
aula --username <your_username> --password <your_password> [COMMAND] [OPTIONS]
```

### CLI Commands

**1. Login:**
Verifies credentials by authenticating with Aula.

```bash
aula --username <your_username> --password <your_password> login
```

**2. Profile:**
Fetches and displays profile information using `get_profile()`.

```bash
aula --username <your_username> --password <your_password> profile
```

**3. Overview:**
Fetches the daily overview using `get_daily_overview()`. By default, it fetches for all children. Specify a single child with `--child-id`.

```bash
# Get overview for all children
aula --username <your_username> --password <your_password> overview

# Get overview for a specific child
aula --username <your_username> --password <your_password> overview --child-id 12345
```
