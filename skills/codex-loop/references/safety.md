# Safety Notes

## What This Tool Optimizes For

- unattended local execution
- durable state
- explicit verification gates
- conservative completion behavior

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

