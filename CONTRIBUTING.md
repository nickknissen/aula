# Contributing to Aula Python Client

Thank you for considering contributing to the Aula Python Client! This document provides guidelines for contributing to the project.

## Code of Conduct

By participating in this project, you are expected to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Install the development dependencies:
   ```bash
   pip install -e .[dev]
   ```
4. Create a feature branch for your changes
5. Make your changes and ensure tests pass
6. Submit a pull request

## Development Environment

### Prerequisites

- Python 3.9+
- pip
- git

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/py-aula.git
   cd py-aula
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. Install the package in development mode with all dependencies:
   ```bash
   pip install -e .[dev]
   ```

## Testing

Run the test suite with pytest:

```bash
pytest
```

Run with coverage:

```bash
pytest --cov=aula --cov-report=term-missing
```

## Linting and Code Style

We use `black` for code formatting and `ruff` for linting. Before submitting a pull request, please run:

```bash
black .
ruff check --fix .
```

## Adding a New Provider

To add a new provider, follow these steps:

1. Create a new Python file in `src/aula/plugins/providers/` with a descriptive name (e.g., `my_provider.py`)

2. Define your provider class:
   ```python
   from ..base import Provider, ProviderRegistry
   from ..http import HTTPClientMixin
   
   @ProviderRegistry.register
   class MyProvider(Provider, HTTPClientMixin):
       """Provider for MyService data."""
       
       # Required attributes
       provider_id = "my_provider"  # Must be unique
       name = "My Provider"
       description = "Fetches data from MyService"
       
       # Optional: Base URL for the provider's API
       base_url = "https://api.example.com/v1"
       
       def __init__(self, auth_token: str, **kwargs):
           """Initialize the provider.
           
           Args:
               auth_token: Aula authentication token
               **kwargs: Provider-specific configuration
           """
           super().__init__(auth_token, **kwargs)
           HTTPClientMixin.__init__(self)
       
       async def fetch_data(self, **kwargs) -> dict:
           """Fetch data from the provider.
           
           Args:
               **kwargs: Additional parameters for the request
               
           Returns:
               dict: The fetched data
           """
           # Example: Make a GET request
           return await self.get("/endpoint", params=kwargs)
   ```

3. Add tests for your provider in `tests/`

4. Update the documentation in `PROVIDERS.md`

5. Submit a pull request

### Provider Configuration

Provider-specific configuration can be set in the configuration file (`~/.config/aula/config.yaml`):

```yaml
providers:
  my_provider:
    base_url: https://api.example.com/v1
    timeout: 30
    # Other provider-specific settings
```

## Pull Request Process

1. Fork the repository and create your feature branch
2. Make your changes
3. Add tests for your changes
4. Ensure all tests pass
5. Update documentation as needed
6. Submit a pull request with a clear description of your changes

## Versioning

We use [SemVer](http://semver.org/) for versioning. For the versions available, see the [tags on this repository](https://github.com/yourusername/py-aula/tags).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Thanks to all contributors who have helped improve this project!
