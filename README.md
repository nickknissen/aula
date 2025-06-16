# Aula: Python Aula API Client Library

Python library for interacting with the Aula platform.

This library provides an asynchronous client (`AulaApiClient`) to fetch data such as profiles, daily overviews, messages, and calendar events from Aula. It also includes a pluggable provider system for extending functionality with additional data sources.

## Features

- **Core API Client**
  - Asynchronous API using `aiohttp`
  - Full type hints
  - Automatic session management
  - Token-based authentication

- **Pluggable Provider System**
  - Extensible architecture for adding new data sources
  - Automatic discovery and registration of providers
  - YAML-based configuration
  - Built-in providers for common services

## Installation

```bash
pip install -e .
```

## Core Functionality

- ✅ Calendar fetching  
- ✅ Post fetching  
- ✅ Messages fetching  
- ✅ Daily Overview fetching  
- ✅ Profile fetching  

## Available Widget Providers

- ✅ 0019 - Biblioteket (Library)  
- ✅ 0030 - MinUddannelse (Assignments)  
- 📋 0001 - EasyIQ - Ugeplan  
- 📋 0004 - Meebook Ugeplan  
- 📋 0029 - MinUddannelse Ugenoter  
- 📋 0047 - Fravær - forældreindberetning  
- 📋 0062 - Huskelisten  
- 📋 0121 - INFOBA Modulordninger til forældre  

For more information about the provider system, see [PROVIDERS.md](PROVIDERS.md).


## Library Usage

Here's a basic example of how to use the `AulaApiClient`:

```python
import asyncio
from aula import AulaApiClient

async def main():
    # Replace with your actual credentials
    username = "your_aula_username"
    password = "your_aula_password"

    client = AulaApiClient(username, password)

    try:
        # Login (required for most operations)
        await client.login()
        print(f"Successfully logged in. API URL: {client.api_url}")

        # Fetch profile information
        profile = await client.get_profile()
        print(f"User: {profile.display_name} (ID: {profile.profile_id})")

        if profile.children:
            print("Children:")
            for child in profile.children:
                print(f" - {child.name} (ID: {child.id})")

                # Fetch daily overview for the first child
                # Note: Only fetching for one child here as an example
                if child == profile.children[0]:
                    overview = await client.get_daily_overview(child.id)
                    print(f"   Overview for {child.name}:")
                    print(f"   - Status: {overview.status_text}")
                    # Add more overview details as needed
        else:
            print("No children found.")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Close the underlying HTTP client session (important!)
        if client._client:
            await client._client.aclose()

if __name__ == "__main__":
    asyncio.run(main())

```

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
