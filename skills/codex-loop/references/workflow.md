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
8. Apply circuit-breaker thresholds for repeated runner or verification failures
9. Apply base backoff plus optional jitter before the next non-terminal iteration
10. Persist iteration history, metrics, blocker codes, and loop status
11. Run local iteration hooks when configured
12. Continue until `completed` or `blocked`

## Doctor

`codex-loop doctor --repair` checks:

- `codex-loop.yaml`
- `tasks/*.md`
- `.codex-loop/state.json`
- `.codex-loop/agent_result.schema.json`

When repair is enabled, it can recreate the schema and realign task state with the current task files.
It can also backfill missing `operator.events` and `operator.cleanup` defaults in `codex-loop.yaml`.
Even without repair, it warns when `operator.cleanup` defaults are aggressive enough to delete all retained artifacts on apply.
Those warnings now include concrete remediation guidance so operators can tighten retention without guessing the right keys.

## Hooks And Metrics

`codex-loop` can run explicit local hooks and persist counters:

- `post_init` after scaffolding
- `pre_iteration` before each task iteration
- `post_iteration` after each task iteration
- `on_completed` and `on_blocked` after terminal outcomes
- hook `failure_policy` can block `post_init`, `pre_iteration`, and `post_iteration`
- `.codex-loop/metrics.json` for aggregate runtime counters
- `status --summary` for the latest blocker code, reason, and current task session id
- `sessions` for a workspace-scoped inventory of known task session ids and their latest prompt/log/run artifacts
- `evidence` for a read-only prompt/log/run bundle tied to the current task, a specific task, or the latest session
- `events --limit N` for a merged timeline across loop history and hook logs
- `events --summary` for grouped counts across the filtered event set
- `events --summary` includes blocker-code counts, blocked task ids, the latest blocked event, and the latest runner or verification failure when those events exist
- `events --task-id ... --event-type ... --json` for focused operator queries and export
- `events --since ... --until ... --output <path>` for time-boxed exports
- `sessions --latest --json` for the most recent session seen by the loop
- `sessions --task-id ... --json` for the latest task-specific session and artifact pointers
- `evidence --task-id ... --json` for the latest evidence bundle of a task without manually opening multiple files
- `evidence --latest --json --output <path>` for exporting a latest-session debug bundle to disk
- `evidence --task-id ... --event-limit N --json` for a bounded task-scoped event snapshot inside the bundle
- `evidence --task-id ... --json --output-dir <dir>` for auto-named debug snapshot exports plus a directory-level `index.json`
- `snapshots --snapshot-dir <dir> [--task-id ...] [--latest] [--json]` for reading that snapshot index back as an operator view
- `snapshots --snapshot-dir <dir> --summary [--json]` for a grouped digest by task, status, selection, blocker code, and latest snapshot markers
- `snapshots --snapshot-dir <dir> --status blocked --since ... --until ... [--json]` for answering recent blocked-snapshot questions without opening bundles individually
- `snapshots --snapshot-dir <dir> --blocker-code no_progress_limit [--json]` for isolating one blocker family across exported snapshots
- `snapshots --snapshot-dir <dir> --sort newest [--json]` for reading filtered snapshots in reverse chronological order
- `snapshots --snapshot-dir <dir> ... --output <path>` for exporting a filtered list or summary after operator-side triage
- `cleanup [--apply] --keep N [--older-than-days N]` for conservative local artifact and stale worktree pruning
- `cleanup --logs-keep ... --runs-keep ... --prompts-older-than-days ...` for per-directory retention overrides
- `operator.cleanup` in `codex-loop.yaml` for default retention policy, with CLI flags overriding config per invocation

## Task Semantics

Tasks are discovered from `tasks/*.md` in filename order. Status lives in `.codex-loop/state.json`, not in the task files themselves.

This means task documents stay readable and stable while the local state file tracks operational progress.
