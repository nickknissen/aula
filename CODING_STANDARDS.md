# Coding standards

The rules a reviewer checks by judgement. Ruff, ty and the pre-commit hooks enforce the mechanical rules, so they are not repeated here. Decisions in `docs/adr/` bind new code as well.

## Code

- Code explains itself. A comment is a last resort, for what the code cannot say.
- A docstring is one line. A public method may add its contract: what it returns and what it raises.
- Why a design was chosen goes in the commit message, the PR or an ADR, not in a comment or docstring.
- API and auth code is async.
- A model is a dataclass on `AulaDataClass`, one file per model in `models/`. It parses with a `from_dict()` classmethod and keeps the original response in `_raw`.
- Parsing is defensive: a response that does not parse logs a warning and does not raise.
- `rich` is optional. Anything that renders with it keeps a plain-text fallback.

## Tests

- Tests mirror `src/aula/`: `src/aula/models/post.py` is tested in `tests/models/test_post.py`.
- Imports go at the top of the file, not inside a test.
- A new test follows the layout of its file: a class per feature where the file groups by class, plain functions where it does not.
- A test docstring explains why, and only when the test name cannot.

## Commits and PRs

- Conventional commits with an optional scope: `feat(cli):`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`.
- Commits, PRs and issues are written in English.
- A PR body says what changed and why, in a few sentences. It has no acceptance-criteria table, test inventory or file-by-file walkthrough.

## Prose

- Prose others read (README, docs, PR bodies, issue comments) uses simple English: short sentences, plain words, no em dashes. Judge only new lines.
- Examples, fixtures and docs use placeholders: `Barn Et`, `Værge Et`, `Lærer Et`, `Skole Et`, `barn0001`, `900001`, `G90001`, `1000001`. The `check-fixture-values` hook catches values shaped like account data. The reviewer also looks for real names, schools and places the hook cannot recognise.
