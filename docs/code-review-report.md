# Code Review Report

**Date:** 2026-02-16
**Scope:** Entire codebase (`src/aula/`, `pyproject.toml`, configuration files)
**Status:** All Critical, High-Impact, Architecture, and Dependency issues have been resolved. Tests remain as future work.

---

## 1. High-Confidence Quick Wins

### 1.1 CRITICAL: CLI is broken against current API client signature
`cli.py:173` and `cli.py:191` call `AulaApiClient(username, password)` with the old 2-argument constructor signature, but `api_client.py:44-46` now requires `(mitid_username, token_storage, debug)`. **The CLI cannot work at all in its current state.** The CLI needs to be updated to construct a `TokenStorage` and pass only `mitid_username`.

### 1.2 Unused import: `BeautifulSoup` in api_client.py
`api_client.py:8` imports `from bs4 import BeautifulSoup` but it is never used anywhere in that file. This is a leftover from a previous refactor. **Remove the import.**

### 1.3 Wrong package name in pyproject.toml
`pyproject.toml:21` declares `packages = [ { include = "py_aula", from = "src" } ]` but the actual package directory is `src/aula/`, not `src/py_aula/`. This is a hatchling-specific key that may be silently ignored by hatchling (which auto-discovers packages), but it is incorrect and confusing. **Fix to `"aula"` or remove the line** (hatchling auto-discovers by default).

### 1.4 Broken entry point in pyproject.toml
`pyproject.toml:24` defines `aula = "aula.__main__:main"` but `__main__.py` has no `main` function -- it calls `cli()` directly at module level. **Change to `aula = "aula.cli:cli"` or add a `main()` wrapper in `__main__.py`.**

### 1.5 `asyncio` imported at bottom of file
`browser_client.py:497` imports `asyncio` at the very end of the file with the comment "Import asyncio at module level for use in async methods". This import is used at lines 207, 218, 258, 268. While it works because it's still at module scope, it violates PEP 8 and is surprising. **Move to the top with other imports.**

### 1.6 Unused dependency: `lxml`
`pyproject.toml:12` lists `lxml>=5.3.0` as a dependency but `lxml` is never imported anywhere in the source code. BeautifulSoup is used with `"html.parser"` (stdlib) throughout. **Remove `lxml` from dependencies** or switch the parser to `"lxml"` for performance.

### 1.7 Dead constants in const.py
`const.py:5` defines `MEEBOOK_API` and `const.py:8-10` defines `CONF_SCHOOLSCHEDULE`, `CONF_UGEPLAN`, `CONF_MU_OPGAVER`. None of these are imported or referenced anywhere else in the codebase. **Remove or mark as planned future use.**

### 1.8 `_get_client` uses `ctx.invoked_subcommand` incorrectly
`cli.py:175` checks `ctx.invoked_subcommand` but `_get_client` is called *from within* subcommands, where `invoked_subcommand` is always `None`. This means the `if command_name != "login"` guard never triggers. **Remove this dead conditional or restructure the login check.**

---

## 2. Code Smells & Cleanup Opportunities

### 2.1 Duplicated HTML-to-text conversion logic
`models.py:214-230` (`Message.content`) and `models.py:314-327` (`Post.content`) both create `html2text.HTML2Text()` instances with similar configuration. The same duplication exists for `content_markdown` at lines 232-248 and 329-339. **Extract a shared utility function** like `html_to_plain(html: str) -> str` and `html_to_markdown(html: str) -> str` into `utils/`.

### 2.2 Duplicated appointment-fetching pattern in api_client.py
`get_mu_tasks` (line 457), `get_ugeplan` (line 473), and `get_huskeliste` (line 515) all follow the same pattern: get bearer token, make a request, extract `data.appointments[0]`, and build an `Appointment`. **Extract a shared helper method** to reduce the ~60 lines of near-identical code.

### 2.3 Credentials stored in plaintext JSON config
`cli.py:104` saves username and password to `~/.config/aula/config.json` in plaintext. This is a security concern. **Consider using the system keyring** (via `keyring` library) or at minimum warn the user about plaintext storage and set restrictive file permissions.

### 2.4 `_get_client` re-fetches credentials redundantly
`cli.py:170-182` calls `get_credentials(ctx)` again even though the `cli()` group function at lines 161-164 already resolves and stores credentials in `ctx.obj`. **Simplify `_get_client` to use `ctx.obj` directly.**

### 2.5 Mixed import styles in cli.py
`cli.py:20` imports `DailyOverview` and `Profile` from `.api_client`, but these are defined in `models.py`. Meanwhile `cli.py:21` correctly imports `Message` and `MessageThread` from `.models`. Then `cli.py:381` uses an absolute import `from aula.utils.table import ...` inside a function body, while all other imports are relative. **Standardize to relative imports and import models from `.models`.**

### 2.6 Bare `Exception` used throughout auth code
`browser_client.py` and `mitid_client.py` raise bare `Exception` in many places (lines 46, 114, 124, 135, 148, 183, etc.) instead of using the custom exception hierarchy defined in `exceptions.py`. **Replace with appropriate `MitIDError`, `NetworkError`, or `SAMLError`.**

### 2.7 No resource cleanup / context manager for AulaApiClient
`AulaApiClient` creates `httpx.AsyncClient` instances but there's no `async with` support. While `close()` exists at `api_client.py:557`, nothing in the CLI calls it, and the class doesn't implement `__aenter__`/`__aexit__`. **Add async context manager protocol** for safer resource management.

### 2.8 `is_logged_in()` makes a full API call
`api_client.py:234-244` calls `get_profile()` to check login status. This makes a full HTTP request and parses the response just to return a boolean. **Consider a lighter check** (e.g., checking token expiry locally).

---

## 3. Structure & Architecture Notes

### 3.1 cli.py contains config management that belongs in its own module
`cli.py:27-55` defines `CONFIG_DIR`, `CONFIG_FILE`, `ensure_config_dir()`, `load_config()`, and `save_config()`. This is infrastructure code that would be better placed in a dedicated `config.py` module, keeping `cli.py` focused on CLI commands.

### 3.2 `utils/__init__.py` is empty
`utils/__init__.py` (line 1) is an empty file. Consider removing it or using it to re-export `build_calendar_table` and `print_calendar_table` for cleaner imports.

### 3.3 `api_client.py` handles both HTTP transport and data parsing
The `AulaApiClient` class (563 lines) is responsible for HTTP requests, response parsing, data model construction, and version negotiation. Consider separating the HTTP transport layer from the data parsing layer for better testability and maintainability.

### 3.4 README example code uses outdated API
`README.md:50-54` shows `AulaApiClient(mitid_username=..., token_file=..., debug=...)` but the current constructor at `api_client.py:44-46` takes `(mitid_username, token_storage, debug)` -- there is no `token_file` parameter. The README also references `overview.status_text` (line 78) which doesn't exist on `DailyOverview`.

### 3.5 CLI docs in README reference old auth model
`README.md:175-207` documents CLI commands using `--username` and `--password` flags, which belong to the old auth model. The library now uses MitID authentication. The CLI section is outdated.

---

## 4. Dependencies & Tooling Review

### 4.1 `lxml` declared but unused
See finding 1.6. `lxml` adds ~30MB to the install for no benefit.

### 4.2 `rich` used but not declared as a dependency
`utils/table.py:5-8` imports `rich` behind a `try/except ImportError` block with a fallback. While this graceful degradation is fine, the fallback plain-text renderer (`table.py:66-74`) uses `print()` directly instead of `click.echo()`, which is inconsistent with the rest of the CLI.

### 4.3 `pytz` can be replaced with stdlib `zoneinfo`
Since the project requires Python 3.10+, `pytz` (`api_client.py:7`, `cli.py:13`) can be replaced with `datetime.timezone` or `zoneinfo.ZoneInfo("CET")` from the standard library, removing a dependency.

### 4.4 `click` has no version pin
`pyproject.toml:15` lists `"click"` with no version constraint. Since the project uses `click.DateTime` (added in Click 8.0), it should specify `click>=8.0`.

### 4.5 No linter, formatter, or type-checker configuration
There is no `ruff`, `black`, `flake8`, `isort`, or `mypy` configuration in `pyproject.toml` or standalone config files. A `.mypy_cache/` directory exists, suggesting mypy has been run manually, but there's no configuration to make it reproducible.

### 4.6 `pycryptodome` used for SRP -- consider noting in security docs
`srp.py` uses `pycryptodome` for AES-GCM operations. The SRP implementation is custom and security-sensitive. There are no comments indicating whether this has been audited or which specification it follows.

---

## 5. Tests & Documentation

### 5.1 No test suite exists
There is no `tests/` directory, no test files, and no test configuration in `pyproject.toml`. The codebase has **zero test coverage**. This is the single highest-impact gap -- particularly critical for the auth flow (`srp.py`, `browser_client.py`, `mitid_client.py`) and data model parsing (`models.py`).

**Suggested priority for test creation:**
1. `models.py` -- pure data parsing, easy to unit test with fixtures
2. `token_storage.py` -- file I/O with clear contract
3. `api_client.py` -- mock HTTP responses to test parsing logic
4. `auth/` -- at minimum, test the SRP math against known vectors

### 5.2 Referenced MIGRATION_GUIDE.md exists but may be stale
`README.md:16` links to `MIGRATION_GUIDE.md`. Verify this guide is still accurate after the `TokenStorage` refactor (the API client constructor changed).

### 5.3 README data model docs point to wrong file
`README.md:118` says "Check `api_client.py` for the specific fields available in each model" but models are defined in `models.py`.

### 5.4 No CI/CD pipeline
There is no `.github/workflows/`, `Makefile`, `tox.ini`, or similar CI configuration. Adding at minimum a lint + type-check workflow would catch issues like the broken CLI signature (finding 1.1) before they are committed.

### 5.5 Version string duplicated
`__init__.py:3` hardcodes `__version__ = "0.1.0"` with the comment "Or fetch dynamically from pyproject.toml". `pyproject.toml:3` also declares `version = "0.1.0"`. These will drift. **Use `importlib.metadata.version("aula")` or a build-system plugin** to single-source the version.

---

## 6. Assumptions & Open Questions

1. **Is the CLI actively maintained?** Finding 1.1 shows the CLI is broken against the current `AulaApiClient` constructor. This may indicate the CLI is not the primary interface and the library is consumed programmatically.

2. **Is `rich` an expected optional dependency?** If so, consider adding it as an optional extra in pyproject.toml: `[project.optional-dependencies] cli = ["rich"]`.

3. **What is the intended auth flow for the CLI?** The CLI still uses `--username`/`--password` flags, but the library now uses MitID (username + app approval). How should the CLI handle the interactive MitID flow?

4. **Are the widget methods (`get_mu_tasks`, `get_ugeplan`, `get_easyiq_weekplan`, `get_huskeliste`) tested or used?** They all follow a pattern that indexes `[0]` on the appointments list without bounds checking. If these are untested, they likely crash on empty responses.

5. **SRP implementation provenance**: `srp.py` contains a custom SRP implementation. Is this ported from an official MitID client or reverse-engineered? Understanding this affects how comfortable maintainers should be modifying it.

6. **Should `comparison == True` on `browser_client.py:274`** be `comparison is True` or just `comparison`? The current form triggers a linter warning and may not behave as expected with truthy non-boolean values.
