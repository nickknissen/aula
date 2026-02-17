# Aula Widget Provider Code Patterns

Concrete code templates for each file touched when adding a new widget provider.
Replace `<PROVIDER>` (uppercase), `<provider>` (lowercase), and `<endpoint_name>` as appropriate.

## 1. const.py - Constants

```python
# Add API base URL alongside existing ones
<PROVIDER>_API = "https://example.com/aulaapi"

# Add widget ID in the widget IDs block
WIDGET_<PROVIDER> = "XXXX"
```

## 2. models/<provider>_<type>.py - Dataclass Models

Every model inherits `AulaDataClass`, carries `_raw: dict | None`, and has a `from_dict()` classmethod.

```python
from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class <Provider>Task(AulaDataClass):
    id: int
    title: str
    content: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "<Provider>Task":
        return cls(
            _raw=data,
            id=data.get("id", 0),
            title=data.get("title", ""),
            content=data.get("content", ""),
        )


@dataclass
class <Provider>DayPlan(AulaDataClass):
    date: str
    tasks: list[<Provider>Task] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "<Provider>DayPlan":
        tasks = [<Provider>Task.from_dict(t) for t in data.get("tasks", [])]
        return cls(_raw=data, date=data.get("date", ""), tasks=tasks)


@dataclass
class <Provider>StudentPlan(AulaDataClass):
    name: str
    unilogin: str
    week_plan: list[<Provider>DayPlan] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "<Provider>StudentPlan":
        week_plan = [<Provider>DayPlan.from_dict(d) for d in data.get("weekPlan", [])]
        return cls(
            _raw=data,
            name=data.get("name", ""),
            unilogin=data.get("unilogin", ""),
            week_plan=week_plan,
        )
```

Key rules:
- `_raw` field is always `dict | None`, `default=None`, `repr=False`
- Use `data.get("key", default)` for safe extraction
- Nested models parse via list comprehension: `[Child.from_dict(x) for x in data.get("items", [])]`
- Fields use Python snake_case; `from_dict` maps from API camelCase keys

## 3. models/__init__.py - Export

Add a single line in alphabetical position:
```python
from .<provider>_<type> import <Provider>TopModel as <Provider>TopModel
```

## 4. api_client.py - API Method

Import the new constant and model, then add a method:

```python
async def get_<provider>_<endpoint>(
    self,
    child_filter: list[str],
    institution_filter: list[str],
    week: str,
    session_uuid: str,
) -> list[<Provider>StudentPlan]:
    """Fetch <Provider> <endpoint> for children."""
    token = await self._get_bearer_token(WIDGET_<PROVIDER>)

    params: list[tuple[str, str]] = [
        ("currentWeekNumber", week),
        ("userProfile", "guardian"),
    ]
    for child in child_filter:
        params.append(("childFilter[]", child))
    for inst in institution_filter:
        params.append(("institutionFilter[]", inst))

    headers = {
        "Authorization": token,
        "Accept": "application/json",
        "sessionUUID": session_uuid,
    }

    resp = await self._request_with_version_retry(
        "get",
        f"{<PROVIDER>_API}/<endpoint_path>",
        params=params,
        headers=headers,
    )
    return [<Provider>StudentPlan.from_dict(s) for s in resp.json()]
```

Notes:
- Header name varies: most use `Authorization` but some (e.g. MoMo/Systematic) use `Aula-Authorization`
- Some providers need extra headers (e.g. `X-Version`, `x-aula-institutionfilter`)
- Some use POST instead of GET (e.g. EasyIQ)
- Response structure varies: some return bare array, some nest under `.get("data", {})`
- Week format varies: some need `YYYY-Wn`, some need `YYYY-Wnn` (leading zero)
- Not all endpoints need a `week` parameter (e.g. MoMo courses)
- Param key names vary: `childFilter[]`/`institutionFilter[]` vs `children`/`institutions`

## 5. cli.py - Click Command

All widget CLI commands share this boilerplate:

```python
@cli.command("<provider>:<command_name>")
@click.option(
    "--week",
    type=str,
    default=None,
    help="Week number (e.g. 8) or full format (2026-W8). Defaults to current week.",
)
@click.pass_context
@async_cmd
async def <provider>_<command_name>(ctx, week):
    """Fetch <Provider> <description> for children."""
    week = _resolve_week(week)
    async with await _get_client(ctx) as client:
        try:
            prof: Profile = await client.get_profile()
        except Exception as e:
            click.echo(f"Error fetching profile: {e}")
            return

        if not prof.children:
            click.echo("No children found in profile.")
            return

        child_filter = [
            str(child._raw["userId"])
            for child in prof.children
            if child._raw and "userId" in child._raw
        ]
        if not child_filter:
            click.echo("No child user IDs found in profile data.")
            return

        institution_filter: list[str] = []
        for child in prof.children:
            if child._raw:
                inst_code = child._raw.get("institutionProfile", {}).get("institutionCode", "")
                if inst_code and str(inst_code) not in institution_filter:
                    institution_filter.append(str(inst_code))

        try:
            profile_context = await client.get_profile_context()
            session_uuid = profile_context["data"]["userId"]
        except Exception as e:
            click.echo(f"Error fetching profile context: {e}")
            return

        try:
            results = await client.get_<provider>_<endpoint>(
                child_filter, institution_filter, week, session_uuid
            )
        except Exception as e:
            click.echo(f"Error fetching <Provider> data: {e}")
            return

        if not results:
            click.echo("No data found.")
            return

        # Display results (adapt per provider)
        from .utils.html import html_to_plain

        for item in results:
            click.echo(f"{'=' * 60}")
            click.echo(f"  {item.name}  |  <Provider> <Label>  [{week}]")
            click.echo(f"{'=' * 60}")
            # ... render item-specific content
            click.echo()
```

Key patterns:
- Command name uses colon separator: `"provider:command"`
- `--week` option and `_resolve_week(week)` only when the endpoint is week-based; omit for non-week endpoints
- Profile + child_filter + institution_filter + session_uuid is always the same boilerplate
- HTML content rendered via `html_to_plain()` from `utils.html`
- Display uses `=` and `-` separators with 2-space indentation
