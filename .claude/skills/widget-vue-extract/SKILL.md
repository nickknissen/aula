---
name: widget-vue-extract
description: >
  Extract endpoint summaries from a specific Aula web widget Vue component using
  sourcemaps and a widget id/key (e.g. 0030 or W0030V0001). Use when user asks to inspect
  widget source for endpoints, request patterns, or provider hints.
---

# Widget Vue Extract

## Trigger

Use this skill for commands like:

- `/widget-vue-extract 0030`
- `/widget-vue-extract W0030V0001`
- "extract endpoints for widget id 0062 from sourcemaps"
- "find the Vue component and APIs for widget W0092V0001"

## Input Format

- Preferred: numeric widget ID, e.g. `0030`.
- Also supported: exact component key, e.g. `W0030V0001`.

Resolution behavior:

- Numeric ID (`0030`) resolves to the highest available component version in sourcemaps
  (for example `W0030V0002` over `W0030V0001`).

## Output Contract

Default output is **endpoint summary only**:

- widget id
- resolved source map URL
- source path (`webpack:///widgets/<id>.vue`)
- extracted endpoint candidates (absolute URLs and relative `/api/...` or `/?method=...`)

Do not dump full component source unless the user explicitly asks.

## Procedure

1. Run extractor against the live portal entrypoint:

```bash
uv run python -m aula.utils.widget_vue_extract 0030 --portal "https://www.aula.dk/portal/#/login"
```

2. Return endpoint summary.
4. If widget not found:
   - tell user it was not present in discovered sourcemaps,
   - recommend loading the widget in browser first and re-running,
   - re-run the same command.

## Notes

- Sourcemaps are discovered by fetching JS assets linked from portal HTML and resolving
  `sourceMappingURL` (header or footer).
- This workflow is source-derived and may include endpoints not currently hit in runtime traffic.
- Cross-check with `docs/widget-implementation.md` to see implementation status.
