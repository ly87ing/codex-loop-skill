# Workflow Reference

## Init

`codex-loop init --prompt "..."` asks Codex to produce:

- a concise project spec
- an implementation plan
- a sequential task list
- verification commands

Those artifacts are written locally so future iterations do not depend on the original conversational context.

## Run

`codex-loop run` performs this loop:

1. Load config and state
2. Recreate missing schema and reconcile state with task files
3. Select the next `ready` or `in_progress` task
4. Create or reuse a temporary worktree
5. Call `codex exec` or `codex exec resume`
6. If resume fails because the session is stale, retry once with a fresh `codex exec`
7. Run local verification commands
8. Persist iteration history and loop status
9. Continue until `completed` or `blocked`

## Doctor

`codex-loop doctor --repair` checks:

- `codex-loop.yaml`
- `tasks/*.md`
- `.codex-loop/state.json`
- `.codex-loop/agent_result.schema.json`

When repair is enabled, it can recreate the schema and realign task state with the current task files.

## Task Semantics

Tasks are discovered from `tasks/*.md` in filename order. Status lives in `.codex-loop/state.json`, not in the task files themselves.

This means task documents stay readable and stable while the local state file tracks operational progress.
