# Widget Namespace Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split widget-provider logic out of `AulaApiClient` into a dedicated module while exposing a simple client API: `client.widgets.get_mu_tasks(...)`.

**Architecture:** Introduce a composed `AulaWidgetsClient` under `src/aula/widgets/client.py`. `AulaApiClient` owns a `widgets` attribute and delegates widget calls to this component. Keep legacy `AulaApiClient` widget methods as wrappers for compatibility, then migrate CLI callsites to `client.widgets.*`.

**Tech Stack:** Python 3.10, async/await, dataclasses, Click, pytest/pytest-asyncio, AsyncMock, ruff.

### Task 1: Add namespace contract tests

**Files:**
- Modify: `tests/test_api_client.py`
- Create: `tests/test_widgets_client.py`

**Step 1: Write failing test for `client.widgets` contract**

```python
class TestWidgetNamespaceContract:
    @pytest.mark.asyncio
    async def test_client_has_widgets_namespace(self):
        client = AulaApiClient(http_client=AsyncMock(), access_token="tok")
        assert hasattr(client, "widgets")

    @pytest.mark.asyncio
    async def test_legacy_widget_method_delegates(self):
        client = AulaApiClient(http_client=AsyncMock(), access_token="tok")
        client.widgets.get_mu_tasks = AsyncMock(return_value=[])
        result = await client.get_mu_tasks("0030", [], [], "2026-W8", "sess")
        assert result == []
        client.widgets.get_mu_tasks.assert_awaited_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api_client.py::TestWidgetNamespaceContract -v`
Expected: FAIL with missing `widgets`/delegation.

**Step 3: Write minimal implementation scaffolding**

Add an initial `widgets` attribute wiring in `AulaApiClient.__init__` and minimal delegation stubs.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api_client.py::TestWidgetNamespaceContract -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_api_client.py tests/test_widgets_client.py src/aula/api_client.py
git commit -m "test: add widget namespace contract tests"
```

### Task 2: Implement `AulaWidgetsClient` token + MU providers

**Files:**
- Create: `src/aula/widgets/__init__.py`
- Create: `src/aula/widgets/client.py`
- Modify: `tests/test_widgets_client.py`

**Step 1: Write failing tests for token and MU providers**

```python
@pytest.mark.asyncio
async def test_get_bearer_token_uses_aula_token_endpoint():
    req = AsyncMock(return_value=HttpResponse(status_code=200, data={"data": "abc"}))
    widgets = AulaWidgetsClient(request_with_version_retry=req, api_url="https://www.aula.dk/api/v22")
    token = await widgets._get_bearer_token("0030")
    assert token == "Bearer abc"

@pytest.mark.asyncio
async def test_get_mu_tasks_parses_tasks():
    ...
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_widgets_client.py -k "token or mu" -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

Implement `AulaWidgetsClient` with methods:
- `_get_bearer_token(...)`
- `get_mu_tasks(...)`
- `get_ugeplan(...)`

Require `resp.raise_for_status()` before parsing.

**Step 4: Run test to verify pass**

Run: `uv run pytest tests/test_widgets_client.py -k "token or mu" -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/aula/widgets/__init__.py src/aula/widgets/client.py tests/test_widgets_client.py
git commit -m "refactor: extract min-uddannelse widget providers"
```

### Task 3: Implement remaining widget providers in widgets module

**Files:**
- Modify: `src/aula/widgets/client.py`
- Modify: `tests/test_widgets_client.py`

**Step 1: Write failing tests**

Cover:
- `get_easyiq_weekplan(...)`
- `get_meebook_weekplan(...)`
- `get_momo_courses(...)`
- `get_library_status(...)`

Assert request shape (URL/params/headers/json), `raise_for_status()` usage, and model parsing.

**Step 2: Run test to verify fail**

Run: `uv run pytest tests/test_widgets_client.py -k "easyiq or meebook or momo or library" -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

Move provider methods from `AulaApiClient` into `AulaWidgetsClient` with unchanged signatures and return types.

**Step 4: Run test to verify pass**

Run: `uv run pytest tests/test_widgets_client.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/aula/widgets/client.py tests/test_widgets_client.py
git commit -m "refactor: extract remaining widget providers"
```

### Task 4: Wire `AulaApiClient.widgets` + compatibility wrappers

**Files:**
- Modify: `src/aula/api_client.py`
- Modify: `tests/test_api_client.py`

**Step 1: Write failing tests for delegation and deprecation behavior**

```python
@pytest.mark.asyncio
async def test_legacy_get_mu_tasks_emits_deprecation_warning(recwarn):
    client = AulaApiClient(http_client=AsyncMock(), access_token="tok")
    client.widgets.get_mu_tasks = AsyncMock(return_value=[])
    await client.get_mu_tasks("0030", [], [], "2026-W8", "sess")
    assert any(issubclass(w.category, DeprecationWarning) for w in recwarn)
```

**Step 2: Run test to verify fail**

Run: `uv run pytest tests/test_api_client.py -k "widget namespace or deprecation" -v`
Expected: FAIL.

**Step 3: Implement wiring and wrappers**

- Instantiate `self.widgets = AulaWidgetsClient(...)` in `__init__`
- Keep legacy methods as async wrappers that:
  1. `warnings.warn(..., DeprecationWarning, stacklevel=2)`
  2. delegate to `self.widgets.<method>(...)`

**Step 4: Run test to verify pass**

Run: `uv run pytest tests/test_api_client.py -k "widget namespace or deprecation" -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/aula/api_client.py tests/test_api_client.py
git commit -m "refactor: add widgets namespace and compatibility wrappers"
```

### Task 5: Migrate CLI callsites to `client.widgets.*`

**Files:**
- Modify: `src/aula/cli.py`

**Step 1: Replace widget callsites**

- `client.get_mu_tasks(...)` -> `client.widgets.get_mu_tasks(...)`
- `client.get_ugeplan(...)` -> `client.widgets.get_ugeplan(...)`
- `client.get_easyiq_weekplan(...)` -> `client.widgets.get_easyiq_weekplan(...)`
- `client.get_meebook_weekplan(...)` -> `client.widgets.get_meebook_weekplan(...)`
- `client.get_momo_courses(...)` -> `client.widgets.get_momo_courses(...)`
- `client.get_library_status(...)` -> `client.widgets.get_library_status(...)`

**Step 2: Verify no old calls remain in CLI**

Run: `uv run python -m pytest tests/test_api_client.py tests/test_auth_flow.py -v`
Run: `rg "client\.get_(mu_tasks|ugeplan|easyiq_weekplan|meebook_weekplan|momo_courses|library_status)" src/aula/cli.py`
Expected: tests PASS and no grep matches.

**Step 3: Commit**

```bash
git add src/aula/cli.py
git commit -m "refactor: migrate cli to widget namespace"
```

### Task 6: Update docs and exports

**Files:**
- Modify: `README.md`
- Modify: `src/aula/__init__.py`

**Step 1: Document new API in README**

Add example for `client.widgets.get_mu_tasks(...)` and deprecation note for legacy direct methods.

**Step 2: Export widget namespace class**

Expose `AulaWidgetsClient` from `src/aula/__init__.py` for type-aware consumers.

**Step 3: Run lint**

Run: `uv run ruff check src/ tests/`
Expected: PASS.

**Step 4: Commit**

```bash
git add README.md src/aula/__init__.py
git commit -m "docs: document widget namespace api"
```

### Task 7: Full verification

**Files:**
- Modify: none

**Step 1: Run full tests**

Run: `uv run pytest`
Expected: PASS.

**Step 2: Run format + lint**

Run: `uv run ruff format src/ tests/`
Run: `uv run ruff check src/ tests/`
Expected: clean.

**Step 3: Final status check**

Run: `git status`
Expected: clean working tree.
