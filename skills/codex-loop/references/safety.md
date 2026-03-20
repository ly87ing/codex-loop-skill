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

- Both the project directory **and** the worktree parent must be added to the Codex trust list before running. `codex-loop run` executes Codex inside an isolated Git worktree at `../.codex-loop-worktrees/<project>/<branch>/` — trusting only the project directory is not enough. Add both to `~/.codex/config.toml`:
  ```toml
  [projects."/absolute/path/to/your-project"]
  trust_level = "trusted"
  [projects."/absolute/path/to/.codex-loop-worktrees"]
  trust_level = "trusted"
  ```
  Without this, `codex exec` will fail with "Not inside a trusted directory".
- Use strong verification commands. Weak verification creates false completion.
- Prefer a clean repository before starting a long unattended run.
- If a task is too broad, rerun `init` with a narrower prompt or edit the generated task docs.
- If Codex repeatedly makes no file changes, the loop should block instead of spinning forever.
- If a saved resume session goes stale or invalid, prefer a controlled fresh exec over blind repeated resume attempts. Transient failures (timeout, network error) are not treated as stale sessions; the session is preserved and the supervisor retries with backoff.
