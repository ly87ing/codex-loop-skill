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

- The project directory must be added to the Codex trust list before running. Add it via `codex` interactively or by adding a `[projects."<absolute-path>"]` entry with `trust_level = "trusted"` to `~/.codex/config.toml`. Without this, every `codex exec` call will fail with "Not inside a trusted directory".
- Use strong verification commands. Weak verification creates false completion.
- Prefer a clean repository before starting a long unattended run.
- If a task is too broad, rerun `init` with a narrower prompt or edit the generated task docs.
- If Codex repeatedly makes no file changes, the loop should block instead of spinning forever.
- If a saved resume session goes stale or invalid, prefer a controlled fresh exec over blind repeated resume attempts. Transient failures (timeout, network error) are not treated as stale sessions; the session is preserved and the supervisor retries with backoff.
