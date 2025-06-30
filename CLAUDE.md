# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python library (`aula`) that provides an asynchronous API client for the Danish Aula platform. The library enables fetching profiles, messages, calendar events, daily overviews, and posts from Aula.

## Development Commands

The project uses `uv` as the package manager and build system:

- **Install dependencies**: `uv sync`
- **Run CLI tool**: `uv run aula --help` or `python -m aula --help`
- **Build package**: `uv build`

## Architecture

### Core Components

- **`api_client.py`**: Main `AulaApiClient` class that handles authentication and API communication
- **`models.py`**: Data models using dataclasses (Profile, Child, DailyOverview, MessageThread, etc.)
- **`cli.py`**: Click-based command-line interface for the library
- **`const.py`**: API URLs and constants for Aula and external widget providers

### Authentication Flow

The client performs multi-step authentication:
1. Initial login page fetch
2. UniLogin authentication
3. API URL discovery
4. Session establishment

### Widget Authentication System

Aula provides external widget plugins that require special authentication tokens. The system works as follows:

1. **Token Acquisition**: Use `_get_widget_auth_token(widget_id)` method to obtain authentication tokens for specific widgets
2. **Widget IDs**: Each external provider has a unique widget ID (e.g., `0001`, `0019`, `0030`)
3. **External API Access**: Use the obtained token to query data from external provider APIs

### Widget Data Examples

The `widget-data-examples/` directory contains real-world examples with folder naming pattern `widgetId-WidgetName`:
- `0019-Biblioteket/`: Library system integration
- `0030-MinUddanelse-Opgaver/`: MinUddannelse assignments

Each widget example contains:
- `request.bash`: HTTP request with authentication token
- `response.json`: Actual API response data
- `widget.vue`: Frontend component showing data presentation

### Key Models

- **Profile**: User profile with children list
- **Child**: Child profile with institution details
- **DailyOverview**: Daily status and presence information
- **MessageThread/Message**: Messaging system data
- **CalendarEvent**: Calendar entries
- **Post**: News/announcement posts

### External APIs

The library integrates with multiple external services defined in `const.py`:
- MinUddannelse API
- Meebook API  
- Systematic API
- EasyIQ API

## Widget System Implementation

The library includes a simple but extensible widget system for external provider integrations:

### Core Components
- **BaseWidget**: Abstract base class defining the widget interface
- **WidgetRegistry**: Simple manual registration system for widgets
- **Widget implementations**: Individual classes for each external provider

### Adding New Widgets
1. Create new widget class inheriting from `BaseWidget` in `src/aula/widgets/`
2. Implement required methods: `widget_id`, `name`, `base_url`, `fetch_data()`
3. Register widget in `src/aula/widgets/__init__.py`
4. Add widget-specific data models as needed

### Usage Examples
```python
# Library usage
client = AulaApiClient(username, password)
await client.login()

# Fetch library data
library_data = await client.get_widget_data("0019", 
    institutions=["G19736"], 
    children=["child123"])

# Fetch assignments
assignments = await client.get_widget_data("0030",
    child_filter=["child123"],
    current_week_number="2025-W24")
```

## CLI Usage

The CLI requires username/password authentication for all commands:
```bash
aula --username <user> --password <pass> [command]
```

Available commands: `login`, `profile`, `overview`, `widget`

### Widget Commands
```bash
# List available widgets
aula widget --list

# Fetch widget data
aula widget 0019 --institutions G19736 --children child123
aula widget 0030 --children child123
```