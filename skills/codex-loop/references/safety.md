# Safety Notes

## What This Tool Optimizes For

- unattended local execution
- durable state
- explicit verification gates
- conservative completion behavior
- recoverable local state drift

## What It Does Not Promise

- perfect recovery from every Codex CLI version quirk
- full YAML parsing without `PyYAML`
- parallel task scheduling
- automatic merge or push after completion

## Operational Guidance

- Use strong verification commands. Weak verification creates false completion.
- Prefer a clean repository before starting a long unattended run.
- If a task is too broad, rerun `init` with a narrower prompt or edit the generated task docs.
- If Codex repeatedly makes no file changes, the loop should block instead of spinning forever.
- If a saved resume session goes stale or invalid, prefer a controlled fresh exec over blind repeated resume attempts. Transient failures (timeout, network error) are not treated as stale sessions; the session is preserved and the supervisor retries with backoff.
