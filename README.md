# codex-loop-skill

`codex-loop` is a local, file-driven autonomous loop for Codex CLI. It turns a prompt into durable project documents, then keeps running Codex against one task at a time until verification passes or the loop blocks on a real limit.

## What It Builds

- `codex-loop init --prompt "..."` generates:
  - `codex-loop.yaml`
  - `spec/`
  - `plan/`
  - `tasks/`
  - `.codex-loop/state.json`
- `codex-loop run`:
  - runs `doctor --repair` before the supervisor starts
  - creates a temporary worktree by default
  - calls `codex exec` / `codex exec resume`
  - falls back to a fresh `codex exec` if a saved resume session is no longer valid
  - blocks on configurable runner-failure or verification-failure circuit breakers
  - can run local `pre_iteration`, `post_iteration`, `on_completed`, and `on_blocked` hooks
  - runs local verification commands after each iteration
  - stops only on `completed` or `blocked`
- `.codex-loop/metrics.json`:
  - persists aggregate counters such as iterations, runner failures, verification failures, resume fallbacks, and blocker summaries
- `codex-loop doctor --repair`:
  - recreates a missing agent result schema
  - reconciles task files with `.codex-loop/state.json`
- `codex-loop status --summary`, `codex-loop events`, and `codex-loop logs tail`:
  - provide concise operator-facing visibility during unattended runs
- `codex-loop cleanup`:
  - prunes old local logs, prompts, runs, and stale non-active worktrees

## Why This Exists

Codex can plan and act, but long-running work needs an external supervisor:

- prompts alone drift across iterations
- interactive approvals break unattended runs
- progress needs durable local state
- completion claims need verification gates

This project keeps the source of truth on disk and treats Codex as a resumable worker.

## Install

From the repository root:

```bash
python3 -m pip install -e .
```

Optional:

```bash
python3 -m codex_loop status --project-dir /path/to/project
```

## Quick Start

Inside a local Git repository:

```bash
codex-loop init --prompt "Build a local autonomous loop that edits code until tests pass."
codex-loop doctor --repair
codex-loop run
codex-loop status --summary
codex-loop events --limit 20
codex-loop events --task-id 001-foundation --event-type iteration:continue --json
codex-loop logs tail --lines 20
codex-loop cleanup --keep 10
codex-loop cleanup --apply --keep 10 --older-than-days 14
```

## Generated Project Layout

```text
your-project/
  codex-loop.yaml
  spec/
    001-project-spec.md
  plan/
    001-implementation-plan.md
  tasks/
    001-*.md
  .codex-loop/
    state.json
    metrics.json
    agent_result.schema.json
    logs/
    runs/
    artifacts/
    hooks/
```

## How Run Works

1. Load `codex-loop.yaml`
2. Run a lightweight repair pass so schema/state/task drift does not wedge the loop
3. Read `tasks/` in filename order
4. Pick the next `ready` or `in_progress` task from `.codex-loop/state.json`
5. Create or reuse a temporary worktree
6. Ask Codex to work only on that task
7. If `codex exec resume` fails because the session is stale, retry once with a fresh `codex exec`
8. Run every command in `verification.commands`
9. Update circuit-breaker counters and metrics
10. Apply structured blocker codes when the loop blocks
11. Run local iteration hooks when configured
12. Record progress, files changed, session metadata, and verification results
13. Continue until all tasks are done or a blocking threshold is reached

## Verification Model

The loop only stops with success when:

- every task is `done`
- all verification commands pass

The loop stops with `blocked` when:

- Codex returns `blocked`
- `max_consecutive_runner_failures` is reached
- `max_consecutive_verification_failures` is reached when enabled
- `max_iterations` is reached
- `max_no_progress_iterations` is reached
- `doctor` finds unrecoverable local state or task file problems

## Safety Model

- The generated config targets `sandbox_mode="workspace-write"`
- The runner requests `approval_policy="never"` through Codex config overrides
- The supervisor keeps `.codex-loop/` local state outside normal task files
- The supervisor can repair a missing schema and task/state drift before entering the loop
- Hook execution is local and explicit through `codex-loop.yaml`; it is never inferred from prompts
- `post_init`, `pre_iteration`, and `post_iteration` can be configured to block on hook failure; terminal hooks are notification-oriented and do not rewrite the final outcome
- The default finish mode is conservative: keep the worktree and branch

## Operator Notes

- `status --summary` now includes `last_blocker_code` and `last_blocker_reason` when the loop blocks.
- `events --limit N` merges `.codex-loop/state.json` history with hook execution logs into a readable timeline, and supports `--task-id`, `--event-type`, and `--json` for focused inspection or export.
- `cleanup` defaults to dry-run mode so operators can review what would be deleted before using `--apply`; `--older-than-days N` keeps recent artifacts and stale worktrees even when they exceed count-based retention.
- `.codex-loop/metrics.json` includes blocker aggregates keyed by blocker code.

## Known Limits

- The generated `codex-loop.yaml` is JSON-compatible YAML. It works today without a YAML dependency, but full YAML editing is only supported when `PyYAML` is installed.
- Codex CLI approval behavior can vary by CLI version. This project asks for `approval_policy="never"`, but some Codex releases have known approval edge cases.
- Some Codex resume failures are only detectable from CLI error text, so session fallback is heuristic rather than protocol-level.
- Task execution is sequential in the first version. There is no parallel task scheduler yet.

## Skill

This repository also ships a Codex skill at `skills/codex-loop/SKILL.md`. The skill tells Codex when to use `codex-loop` and how to move between `init`, review, and `run`.

## Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Compile check:

```bash
python3 -m compileall src
```
