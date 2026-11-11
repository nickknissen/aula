# Aula

[![PyPI](https://img.shields.io/pypi/v/aula)](https://pypi.org/project/aula/)
[![Python](https://img.shields.io/pypi/pyversions/aula)](https://pypi.org/project/aula/)
[![License](https://img.shields.io/pypi/l/aula)](LICENSE)

Unofficial async Python client for the Danish school platform **aula.dk**. The project delivers:

1. **Async Python API client** — programmatic access to profiles, messages, calendar, posts, and more
2. **CLI** — read messages, calendar, posts, presence, and widget data from the terminal
3. **AI agent skill** — teach [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or [OpenCode](https://opencode.ai) to query school data

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Authentication](#authentication)
- [CLI](#cli)
- [Configuration](#configuration)
- [AI Agent Integration](#ai-agent-integration)
- [Project Structure](#project-structure)
- [Attribution](#attribution)
- [License](#license)

## Installation

```bash
pip install aula
# or with uv
uv add aula
```

**Requirements:** Python >= 3.14, MitID username and MitID app.

### Run without installing

Use `uvx` to run the CLI directly from PyPI without a permanent install:

```bash
uvx aula --username johndoe messages --limit 5
```

### Install from Source

```bash
git clone https://github.com/nickknissen/aula.git
cd aula
pip install -e .
```

## Quick Start

```python
import asyncio
from aula import FileTokenStorage
from aula.auth_flow import authenticate_and_create_client

async def main():
    token_storage = FileTokenStorage(".aula_tokens.json")
    async with await authenticate_and_create_client("your_mitid_username", token_storage) as client:
        profile = await client.get_profile()
        print(profile.display_name)
        for child in profile.children:
            overview = await client.get_daily_overview(child.id)

asyncio.run(main())
```

To log in through the MitID app from your own terminal program, `TerminalQRDisplay` shows the two QR halves the way `aula login` does:

```python
from aula import FileTokenStorage, TerminalQRDisplay
from aula.auth_flow import authenticate_and_create_client

display = TerminalQRDisplay()
try:
    client = await authenticate_and_create_client(
        "your_mitid_username",
        FileTokenStorage(".aula_tokens.json"),
        on_qr_codes=display.show,
        on_qr_done=display.done,
    )
finally:
    display.stop()
```

Pass `header`, `part_label` (`{part}` becomes 1 or 2) or `done_message` to print your own text, or `None` to print nothing there.

Key methods on `AulaApiClient`: `get_profile()`, `get_daily_overview(child_id)`, `get_message_threads()`, `get_messages_for_thread(thread_id)`, `get_calendar_events(...)`, `get_posts(...)`, `get_groups(...)`, `get_message_folders(...)`, `search(...)`, `update_presence_template(...)`, `update_presence_status(...)`, `get_profile_master_data(...)`, `get_secure_documents(...)`, `get_consent_responses(...)`, `get_auto_reply()`, `get_vacation_registrations(...)`, `get_notification_settings()`, `keep_alive()`. See `src/aula/api_client.py` for the full list.

### Widget API (Namespace)

Widget integrations are available via the namespaced widgets client on `AulaApiClient`:

```python
from aula.widgets import WidgetContext

profile = await client.get_profile()
ctx = WidgetContext.from_children(profile.children, await client.get_profile_context())
tasks = await client.widgets.get_mu_tasks(
    widget_id="0030",  # WIDGET_MIN_UDDANNELSE_TASKS
    child_filter=ctx.child_filter,
    institution_filter=ctx.institution_filter,
    week="2026-W8",
    session_uuid=ctx.session_uuid,
)
```

Pass a subset of `profile.children` to scope the call to those children. For the EasyIQ calls, `easyiq_child_user_ids(profile_context)` from `aula.widgets` gives the `all_child_user_ids` argument.

Use the `client.widgets.*` namespace for widget calls (for example: `get_mu_tasks`, `get_ugeplan`, `get_easyiq_weekplan`, `get_meebook_weekplan`, `get_docendo_weekplan`, `get_momo_courses`, `get_library_status`).

Legacy direct widget methods on `AulaApiClient` are deprecated and will be removed in a future release. Migrate to `client.widgets.<method>(...)`.

## Authentication

### What You Need

- **MitID username** — your MitID username (not your Aula username). Find it at [mitid.dk](https://mitid.dk/).
- **A MitID authenticator** — either the MitID app on your phone, or a MitID kodeviser (code display device) plus your MitID password.

### Authentication Methods

Pick with `--auth-method` (or the `AULA_AUTH_METHOD` env var):

| Method | Flag | What happens |
|---|---|---|
| MitID app | `--auth-method app` (default) | A QR code is printed in the terminal for you to scan. It comes in two halves that take turns in the same spot, so hold the app on it until both have been read. If your app asks for a code instead of a scan, that code is printed too. |
| MitID kodeviser | `--auth-method token` | You're asked for the 6 digits on your kodeviser, then your MitID password. |

MitID chip and audio code readers (kodeoplæser) are not supported. If your account offers one, it's listed in a warning at `-v` and the login falls back to whatever else you have.

### First Login

On first run you have to approve the login in your MitID app. With the default `app` method the terminal shows the QR code to scan:

```
Scan with your MitID app: open it, start the QR scanner, and hold the
camera steady on the code below. The code comes in two halves that take
turns in the same spot, so keep the phone still until the app has read
both. It stays quiet until then, and asks you to approve the login once
it has them.

QR code 1 of 2:
█▀▀▀▀▀▀▀███▀▀▀▀███▀▀▀█▀█▀▀▀▀█▀█▀▀▀▀▀▀▀█
█ █▀▀▀█ █ ██ ▀▄ ███▄ ▀▀▀█▀▄█▀▀█ █▀▀▀█ █
...
```

The two codes are halves of one value, not two things to choose between. The first half holds for two seconds, then the halves swap every second in the same spot. Nothing happens in the app until it has read both, so keep the phone still rather than moving it away after the first one. Once the app has them, the codes disappear and the app asks you to approve the login.

If your app asks for a code to type instead of a scan, that code is printed instead of the QR code.

Tokens are saved to the storage file and reused on subsequent runs — no authenticator interaction needed until they expire. `aula logout` removes them and forces a fresh MitID login; the saved MitID username is kept.

Another program can run `aula login` and then use the saved session:

```bash
aula --token-file ./tokens.json --identity 2 --output json login --force
# {"status": "ok", "api_url": "...", "identity": 2}
```

`--token-file` (or `AULA_TOKEN_FILE`) sets where the session is saved, for every command including `logout`. `--identity` (or `AULA_MITID_IDENTITY`) picks one of several MitID identities without asking, 1 being the first. A number beyond the last identity is an error. `login --force` logs in through MitID even when the saved session still works. A saved session is reused as it is, so add `--force` to switch identity. The JSON output names the identity only when there was one to choose.

For the kodeviser method you can skip the prompts:

```bash
export AULA_MITID_PASSWORD='...'      # or --password
aula --auth-method token --token-code 123456 messages
```

The kodeviser code rotates, so `--token-code` is only useful for a single run. The password is never written to the config file; supply it per-run or via the environment.

### If Login Is Blocked

If you are outside Denmark, the login can be stopped before MitID is reached:

```
Login blocked: you are most likely not connecting from a Danish IP address.

STIL diverted the redirect to MitID into a security check on
security-check.stil.dk. ...
```

STIL puts a bot check in front of the UniLogin broker. Getting past it needs a browser that runs JavaScript, so this client cannot complete a login while the check is active.

The check does not fire for everyone. Every report so far comes from outside Denmark: logins from a Danish IP address are let through, while logins from other countries are challenged. If you are outside Denmark, a connection with a Danish IP address is the only known workaround. See [issue #43](https://github.com/nickknissen/aula/issues/43).

### Token Security

Tokens provide full access to your Aula account — treat them like passwords and never commit token files to version control.

Application diagnostics redact recognized credential fields and URL query values,
and omit raw authentication HTML. This does not anonymize personal content:
debug logs can still contain school data and should be reviewed before sharing.

### How It Works

For a detailed breakdown of the authentication flow (OAuth + SAML + MitID), session cookies, and how this library differs from the browser login, see [docs/aula-authentication.md](docs/aula-authentication.md).

## CLI

Install as a standalone tool:

```bash
# with uv (recommended)
uv tool install aula

# or with pip
pip install aula
```

Then run:

```bash
aula --username <your_mitid_username> [COMMAND]
```

The username can also be set via the `AULA_MITID_USERNAME` environment variable or a [config file](#configuration).

### Core

| Command | Description |
|---|---|
| `aula login` | Verify credentials (`--force` to log in through MitID again) |
| `aula logout` | Forget the cached session and log in through MitID again |
| `aula profile` | Show profile and children |
| `aula profile-details` | Extended profile info (email, phone, address) |
| `aula overview` | Daily overview for all children |
| `aula daily-summary` | Today's schedule, homework & messages |
| `aula weekly-summary` | Full week overview with provider data |

### Messages

| Command | Description |
|---|---|
| `aula messages` | Recent message threads |
| `aula mark-read THREAD_ID...` | Mark threads as read (writes to Aula, own mailbox only; see below) |
| `aula auto-reply` | View auto-reply status |
| `aula contacts` | Contact list |
| `aula notifications` | Recent notifications |
| `aula notification-settings` | View notification preferences |
| `aula search` | Search documents across Aula |

`aula mark-read` moves a thread's read marker to its newest message, as the app does
when a thread is opened, and checks that Aula took it. The marker targets the newest
message found while reading; messages arriving afterward may remain unread. A thread
can begin with events (recipients added or removed) that are not messages, so it
reads up to 50 pages of 20. Running out of that scan limit raises an error, while a
thread that holds only events is returned unmarked and makes the command exit 1.
Only threads in your own mailbox are handled; common and OTP inboxes are refused.
It tries every thread given and exits with a non-zero code if any was not marked.

For exhaustive reads, use `search_messages_result()`,
`get_all_message_threads_result(cutoff_date)`, or
`get_all_messages_for_thread_result(thread_id)`. Each returns `PaginationResult`
with `items`, `complete`, and `termination_reason`. The existing list methods
remain available and warn when returning partial results. Records with stable IDs
are deduplicated in first-seen order.

| Termination reason | Complete | Meaning |
| --- | --- | --- |
| `exhausted` | Yes | Exhaustion without contradictory available totals |
| `cutoff` | Yes | Requested thread date cutoff reached |
| `max_pages` | No | Safety cap reached |
| `no_progress` | No | Repeated page or no new identifiable records |
| `inconsistent_total` | No | Available totals disagree with observed results |

Request failures still raise, including on later pages. `aula messages --search`
returns a JSON object containing these three fields instead of a bare list.
Incomplete searches print a warning in text mode and exit 1 in both modes.
Message image exports report incomplete searches/thread reads through progress
messages and an optional `on_incomplete` callback while preserving their
`(downloaded, skipped)` return tuple. The download CLI includes `message_export`
completeness and issues in JSON, and exits 1 for incomplete message exports.

### Calendar

| Command | Description |
|---|---|
| `aula calendar` | Calendar events |
| `aula meetings` | Booked parent meetings at their selected times (next 100 days) |
| `aula important-dates` | Important dates |
| `aula birthdays` | Birthday events |
| `aula vacations` | Vacation registrations |

`aula meetings --child-id 12345 --start-date 2026-11-01 --end-date 2026-12-01`
shows that child's booked parent meetings in November. The end date is exclusive;
without `--child-id`, all children are included. Text times use Europe/Copenhagen.
JSON output includes the child, meeting ID, location and exact booked timestamps.

The Python API is `await client.get_meeting_bookings(child.id, start, end)`, with
timezone-aware datetime bounds and an exclusive end. It returns `MeetingBooking`
models for actual appointments, excluding unbooked invitations and other children's
answers. Long ranges are fetched in chunks; a rejected request raises instead of
returning a partial list.

For a per-child view, `await client.get_calendar_events_by_child(child_ids, start, end)`
returns a dict of `CalendarEvent` lists keyed by `Child.id`, with timezone-aware
bounds covering whole days. Aula returns an event several of your children share
once, such as twins' lessons or a school event for siblings, so it is listed under
every child it names. Booked parent meetings show at each child's booked slot.
`CalendarEvent.belongs_to_profiles` names every child an event belongs to;
`belongs_to` is only the first.

### Presence

| Command | Description |
|---|---|
| `aula presence` | Presence registrations and states |
| `aula presence-templates` | Planned entry/exit times |
| `aula update-presence` | Update pickup/drop-off times |
| `aula report-sick` | Report a child sick today, or take it back (`--undo`) |
| `aula register-absence` | Register a planned absence (ferie/fri) from `--from` to `--to` |

`aula register-absence --from 2026-12-21 --to 2026-12-23 --comment Ferie` registers
a planned absence for every child, or for the ones given with `--child` (repeatable).
Dates follow the guardian portal's rules: the start is today or later in Denmark, the
end is on or after the start and at most one calendar year later, and the comment is
at most 250 characters. A child is skipped with a reason when Aula says absence
registration is not editable for guardians, or that you have neither custody of nor
extended access to the child. When the presence configuration cannot be read, or has
no entry for a child, this is logged (shown with `-v`) and the absence is sent, so Aula
decides; `report-sick` works the same way. The command asks before it writes; `-y`
skips the question and `--output json` requires it. It exits 1 when nothing was
registered.

The Python API is `await client.add_vacation(child_ids, start, end, comment)`, with
`Child.id` values and `date` bounds. It checks the dates and comment, not
permissions, and returns True once Aula accepts the absence.

### Content

| Command | Description |
|---|---|
| `aula posts` | Posts and announcements |
| `aula groups` | Groups and group members (`--search` to search by name) |
| `aula documents` | Secure documents (`--common` for institution files) |
| `aula consents` | Consent responses |
| `aula download-images` | Download images from gallery/posts/messages |

Image exports keep an `.aula-archive.json` manifest in the output directory to
recognize previously downloaded attachments by source identity. Distinct files
with equal names receive separate paths. Keep the manifest with the archive for
reruns. Existing files without manifest entries are preserved; the attachment is
downloaded beside them because its identity cannot be established from its name.

### Widgets

| Command | Description |
|---|---|
| `aula widgets` | List available widgets |
| `aula mu:opgaver` | Min Uddannelse tasks |
| `aula mu:ugeplan` | Min Uddannelse weekly letter |
| `aula easyiq:ugeplan` | EasyIQ weekly plan |
| `aula easyiq:homework` | EasyIQ homework |
| `aula meebook:ugeplan` | Meebook weekly plan |
| `aula docendo:ugeplan` | Docendo weekly plan, matched to children by class |
| `aula momo:forløb` | MoMo courses |
| `aula momo:huskeliste` | MoMo reminders |
| `aula library:status` | Library loans & reservations |

### Global flags

| Flag | Description |
|---|---|
| `--username` | MitID username (or `AULA_MITID_USERNAME` env var) |
| `--output text\|json` | Output format (or `AULA_OUTPUT` env var) |
| `--auth-method app\|token` | MitID auth method (or `AULA_AUTH_METHOD` env var) |
| `--password` | MitID password for `--auth-method token` (or `AULA_MITID_PASSWORD` env var) |
| `--token-code` | 6 digits from your MitID kodeviser (or `AULA_MITID_TOKEN_CODE` env var) |
| `--token-file` | Where the session is saved (or `AULA_TOKEN_FILE` env var), default `~/.config/aula/tokens.json` |
| `--identity` | Which MitID identity to use when there are several, 1 being the first (or `AULA_MITID_IDENTITY` env var) |
| `-v` / `-vv` / `-vvv` | Increase verbosity (warning / info / debug) |
| `--version` | Print the installed version and the Python it runs on |

### JSON output

All commands support `--output json` for machine-readable output:

```bash
aula --output json messages --unread
aula --output json daily-summary --child "Emma"
aula --output json calendar --start-date 2026-03-10
```

### Examples

```bash
aula --username johndoe messages --limit 5
# or without installing
uvx aula --username johndoe messages --limit 5
```

## Configuration

`~/.config/aula/config.json`:

```json
{
  "mitid_username": "your_mitid_username"
}
```

The username is saved automatically on first login. CLI flags and environment variables take precedence over the config file.

## AI Agent Integration

The CLI is designed to work with AI coding agents like [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and [OpenCode](https://opencode.ai). The `agent-setup` command installs a skill that teaches agents how to query Aula for school data.

```bash
# Install for the current project
aula agent-setup

# Install globally (all projects)
aula agent-setup --global
```

This creates a `SKILL.md` following the [Agent Skills](https://agentskills.io) open standard under `.claude/skills/aula/`, which is read by both Claude Code and OpenCode. Once installed, agents can invoke `/aula` or automatically use the CLI when you ask about school data.

## Project Structure

```
src/aula/
  api_client.py             # Async API client (main entry point)
  cli.py                    # Click CLI commands
  auth_flow.py              # High-level auth orchestration
  config.py                 # CLI config (~/.config/aula/config.json)
  token_storage.py          # Token persistence (ABC + file impl)
  auth/                     # MitID authentication
    mitid_client.py         # 7-step OAuth+SAML+MitID flow
    browser_client.py       # Low-level MitID protocol (QR, OTP, SRP)
    srp.py                  # Secure Remote Password with AES-GCM
  models/                   # API data models (one file per model)
  utils/                    # HTML helpers, table rendering, downloads
tests/                      # Mirrors src/aula/ structure
```

## Attribution

- Aula API usage was inspired by the [scaarup/aula](https://github.com/scaarup/aula) Home Assistant integration.
- MitID authentication was inspired by the [Hundter/MitID-BrowserClient](https://github.com/Hundter/MitID-BrowserClient) project.
- EasyIQ widget integration (weekplan and homework) was inspired by the [esbenwiberg/easyiq](https://github.com/esbenwiberg/easyiq) Home Assistant integration.
- Additional API endpoints were discovered via the [eisbaw/aulalibre](https://github.com/eisbaw/aulalibre) Rust client, which reverse-engineered the Aula Android app.

## License

MIT
