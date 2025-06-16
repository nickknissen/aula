# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial implementation of the pluggable provider system
- Base `Provider` class and `ProviderRegistry` for managing providers
- `HTTPClientMixin` for making HTTP requests with Aula auth
- Automatic provider discovery and registration
- Configuration management with YAML support
- Example providers:
  - `BiblioteketProvider` for library data
  - `MinUddanelseProvider` for assignments data
- CLI commands for managing and interacting with providers
- Comprehensive test suite
- Documentation and contribution guidelines

### Changed
- Updated project structure to support plugins
- Improved error handling and logging

### Fixed
- Various bug fixes and improvements

## [0.1.0] - YYYY-MM-DD

### Added
- Initial release of the Aula Python client library
- Basic API client for interacting with Aula
- Support for fetching profiles, messages, calendar events, etc.

[Unreleased]: https://github.com/nickknissen/py-aula/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nickknissen/py-aula/releases/tag/v0.1.0
