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
2. Select the next `ready` or `in_progress` task
3. Create or reuse a temporary worktree
4. Call `codex exec` or `codex exec resume`
5. Run local verification commands
6. Persist iteration history and loop status
7. Continue until `completed` or `blocked`

## Task Semantics

Tasks are discovered from `tasks/*.md` in filename order. Status lives in `.codex-loop/state.json`, not in the task files themselves.

This means task documents stay readable and stable while the local state file tracks operational progress.

