# Aula Data Providers

This document describes how to use and extend the Aula Data Providers system.

## Overview

The Aula Data Providers system allows you to fetch data from various external services that integrate with Aula. The system is designed to be extensible, making it easy to add support for new data sources.

## Available Providers

### Biblioteket

Fetches library data including loans and reservations.

**Provider ID**: `biblioteket`

**Example Usage**:

```bash
aula provider fetch biblioteket
```

### MinUddanelse

Fetches assignments and homework data.

**Provider ID**: `minuddannelse`

**Example Usage**:

```bash
aula provider fetch minuddannelse
```

## Creating a New Provider

To create a new provider, follow these steps:

1. Create a new Python file in `src/aula/plugins/providers/` with a name like `your_provider.py`
2. Define a class that inherits from `Provider` and implements the required methods
3. Add the `@ProviderRegistry.register` decorator to register your provider
4. Implement the `fetch_data` method to fetch and return data

### Example Provider

```python
from typing import Any, Dict, List, Optional

from ..base import Provider, ProviderRegistry
from ..http import HTTPClientMixin

@ProviderRegistry.register
class MyProvider(Provider, HTTPClientMixin):
    """Provider for MyService data."""

    provider_id = "myservice"
    name = "My Service"
    description = "Fetches data from MyService"

    # Base URL for the provider's API
    base_url = "https://api.myservice.com/v1"

    def __init__(self, auth_token: str, **kwargs):
        super().__init__(auth_token, **kwargs)
        HTTPClientMixin.__init__(self)

    async def fetch_data(self, **kwargs) -> Dict[str, Any]:
        """Fetch data from the provider."""
        # Your implementation here
        return await self.get("/endpoint", params=kwargs)
```

## CLI Commands

### List Available Providers

```bash
aula provider list
```

### Fetch Data from a Provider

```bash
aula provider fetch <provider_id> [options]
```

### Provider-Specific Options

Some providers accept additional options. Use `--help` to see available options:

```bash
aula provider fetch <provider_id> --help
```

## Testing

To test a provider, you can use the `fetch` command with the `--debug` flag:

```bash
aula --debug provider fetch <provider_id>
```

## Contributing

1. Fork the repository
2. Create a new branch for your feature
3. Add tests for your changes
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
