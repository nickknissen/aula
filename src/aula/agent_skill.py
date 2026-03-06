"""Generate the SKILL.md content for AI agent integration."""


def generate_skill_md() -> str:
    return """\
---
name: aula
description: >
  Query the Danish school platform aula.dk for children's schedules, messages,
  homework, attendance, and more.  Use when the user asks about school data,
  children's day, homework, messages from school, or weekly plans.
  Always use --output json for structured data.
---

# Aula CLI – Agent Reference

The `aula` CLI fetches data from the Danish school platform **aula.dk**.
Always pass `--output json` (or set `AULA_OUTPUT=json`) to get
machine-readable JSON instead of human-formatted text.

## Authentication

Authentication uses MitID (Danish national identity).  The CLI caches
tokens automatically.  If the session has expired the CLI will prompt
interactively — there is no way to authenticate non-interactively.

Set the username once so it is not prompted every time:

```bash
export AULA_MITID_USERNAME="<username>"
# or
aula --username "<username>" <command>
```

## Global options

| Flag | Description |
|------|-------------|
| `--output json` | **Always use this.** Returns structured JSON. |
| `--username TEXT` | MitID username (or `AULA_MITID_USERNAME` env var). |
| `--auth-method [app\\|token]` | MitID method: `app` (QR/push) or `token`. |
| `-v` / `-vv` / `-vvv` | Increase log verbosity. |

## Commands

### Quick overview commands (start here)

#### `daily-summary` — Today's full picture
```bash
aula --output json daily-summary
aula --output json daily-summary --child "Emma" --date 2026-03-10
```
Returns: `{status, calendar_events, homework_due_today, unread_messages}`

#### `weekly-summary` — Week at a glance
```bash
aula --output json weekly-summary
aula --output json weekly-summary --child "Emma" --week 10 --provider all
```
Returns: `{week, calendar_events, unread_messages, mu_tasks, meebook_weekplan, ...}`
Providers: `mu_opgaver`, `mu_ugeplan`, `meebook`, `easyiq`, `easyiq_homework`, `all`.

### Core data commands

#### `profile` — Parent & children info
```bash
aula --output json profile
```
Returns: `{display_name, profile_id, children: [{name, id, profile_id, institution_name}], ...}`

#### `overview` — Check-in status
```bash
aula --output json overview
aula --output json overview --child-id 12345
```
Returns: list of daily overview objects with status, check-in/out times, location.

#### `calendar` — Schedule / events
```bash
aula --output json calendar
aula --output json calendar --start-date 2026-03-10 --end-date 2026-03-14
```
Returns: list of calendar event objects.

#### `messages` — Message threads
```bash
aula --output json messages
aula --output json messages --unread --limit 10
aula --output json messages --search "field trip"
```
Returns: list of thread objects (with nested messages for thread view).

#### `notifications` — Recent notifications
```bash
aula --output json notifications --limit 10
```
Returns: list of notification objects.

#### `posts` — School posts / announcements
```bash
aula --output json posts --limit 5
```
Returns: list of post objects.

#### `presence-templates` — Planned entry/exit times
```bash
aula --output json presence-templates
aula --output json presence-templates --from-date 2026-03-10 --to-date 2026-03-14
```
Returns: list of presence template objects with day templates.

### Homework & weekly plan providers

#### `mu:opgaver` — Min Uddannelse tasks
```bash
aula --output json mu:opgaver
aula --output json mu:opgaver --week 10
```

#### `mu:ugeplan` — Min Uddannelse weekly letter
```bash
aula --output json mu:ugeplan --week 10
```

#### `easyiq:ugeplan` — EasyIQ weekly plan
```bash
aula --output json easyiq:ugeplan --week 10
```

#### `easyiq:homework` — EasyIQ homework
```bash
aula --output json easyiq:homework --week 10
```

#### `meebook:ugeplan` — Meebook weekly plan
```bash
aula --output json meebook:ugeplan --week 10
```

#### `momo:forløb` — MoMo courses
```bash
aula --output json momo:forløb
```

#### `momo:huskeliste` — MoMo reminders
```bash
aula --output json momo:huskeliste
```

### Other commands

#### `widgets` — List available widgets
```bash
aula --output json widgets
```

#### `library:status` — Library loans & reservations
```bash
aula --output json library:status
```

#### `download-images` — Download images
```bash
aula --output json download-images --since 2026-01-01
aula --output json download-images --since 2026-01-01 --source gallery --tags "classphoto"
```
Returns: `{downloaded: N, skipped: N}`

#### `login` — Authenticate only
```bash
aula --output json login
```
Returns: `{status: "ok", api_url: "..."}`

## Tips

- `--week` accepts a bare number (e.g. `10`) or full ISO format (`2026-W10`).
- Dates are always `YYYY-MM-DD`.
- `--child` on summary commands does partial, case-insensitive matching.
- Not all widget providers are available at every school — if a provider
  returns an empty list, the school likely does not use that provider.
- Use `daily-summary` or `weekly-summary` first to get a broad picture,
  then drill into specific commands for details.
"""
