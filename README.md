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
- `codex-loop daemon start|status|stop`:
  - starts a detached local watchdog around `run --continuous`
  - writes `.codex-loop/daemon.json`, `.codex-loop/daemon-heartbeat.json`, and `.codex-loop/daemon-watchdog.json`
  - restarts the worker when the child exits unexpectedly or the heartbeat goes stale
  - applies a bounded restart policy with backoff so crash loops do not respawn forever without visibility
  - reports pid, phase, cycle, restart policy, restart count, heartbeat staleness, and log path for operator inspection
- `codex-loop service install|status|uninstall`:
  - installs a per-project macOS `launchd` agent under `~/Library/LaunchAgents`
  - keeps the loop alive across shell exits and future logins with `RunAtLoad` and `KeepAlive`
  - writes `.codex-loop/service.json`, `.codex-loop/service-heartbeat.json`, `.codex-loop/service-watchdog.json`, and `.codex-loop/service.log`
  - preserves `PATH`, `HOME`, `SHELL`, and `CODEX_HOME` for the long-running service process
  - refuses to install while a local `daemon` worker is already running, to avoid dual writers against the same loop state
  - confirms the job is actually unloaded before cleaning local metadata on uninstall
- `.codex-loop/metrics.json`:
  - persists aggregate counters such as iterations, runner failures, verification failures, resume fallbacks, and blocker summaries
- `codex-loop doctor --repair`:
  - recreates a missing agent result schema
  - reconciles task files with `.codex-loop/state.json`
  - restores missing `operator.events` and `operator.cleanup` defaults in `codex-loop.yaml`
  - warns when cleanup defaults are aggressive enough to delete all retained artifacts on apply, with concrete remediation guidance
- `codex-loop status --summary`, `codex-loop sessions`, `codex-loop events`, and `codex-loop logs tail`:
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
codex-loop run --continuous --retry-blocked --cycle-sleep-seconds 60
codex-loop daemon start --retry-blocked --cycle-sleep-seconds 60
codex-loop daemon status --json
codex-loop daemon stop
codex-loop service install --retry-blocked --cycle-sleep-seconds 60
codex-loop service status --json
codex-loop service uninstall
codex-loop status --summary
codex-loop sessions
codex-loop sessions --latest --json
codex-loop sessions --task-id 001-foundation --json
codex-loop evidence --task-id 001-foundation --json
codex-loop evidence --latest --json --output ./evidence.json
codex-loop evidence --task-id 001-foundation --event-limit 5 --json
codex-loop evidence --task-id 001-foundation --json --output-dir ./snapshots
codex-loop snapshots --snapshot-dir ./snapshots
codex-loop snapshots --snapshot-dir ./snapshots --summary
codex-loop snapshots --snapshot-dir ./snapshots --latest --json
codex-loop snapshots --snapshot-dir ./snapshots --status blocked --since 2026-03-20T00:00:00+00:00 --until 2026-03-21T00:00:00+00:00 --json
codex-loop snapshots --snapshot-dir ./snapshots --blocker-code no_progress_limit --json
codex-loop snapshots --snapshot-dir ./snapshots --sort newest --json
codex-loop snapshots --snapshot-dir ./snapshots --latest-blocked --json
codex-loop snapshots --snapshot-dir ./snapshots --summary --group-by blocker --json
codex-loop snapshots --snapshot-dir ./snapshots --summary --output ./snapshots-summary.txt
codex-loop snapshots --snapshot-dir ./snapshots --latest-blocked --json --output-dir ./snapshot-reports
codex-loop snapshots-exports --exports-dir ./snapshot-reports --latest --json
codex-loop snapshots-exports --exports-dir ./snapshot-reports --status blocked --summary --group-by render --json
codex-loop snapshots-exports --exports-dir ./snapshot-reports --summary --group-by render --output-dir ./snapshot-export-reports
codex-loop events --limit 20
codex-loop events --summary --json
codex-loop events --task-id 001-foundation --event-type iteration:continue --json
codex-loop events --since 2026-03-19T00:00:00+00:00 --until 2026-03-20T00:00:00+00:00 --output ./events.json
codex-loop logs tail --lines 20
codex-loop cleanup --keep 10
codex-loop cleanup --apply --keep 10 --older-than-days 14
codex-loop cleanup --logs-keep 20 --prompts-older-than-days 30
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

For longer unattended runs, `codex-loop run --continuous --retry-blocked` adds an outer retry loop around the normal supervisor run. When a cycle blocks, it requeues blocked tasks, sleeps, and starts the next cycle until completion or `--max-cycles` is reached.

For a detached local worker, `codex-loop daemon start --retry-blocked --cycle-sleep-seconds 60` now launches a watchdog parent process in the background. That parent records watchdog metadata, starts the real continuous worker, and restarts it if the child exits unexpectedly or stops updating its heartbeat.

For a longer-lived macOS login service, `codex-loop service install --retry-blocked --cycle-sleep-seconds 60` writes a `launchd` plist under `~/Library/LaunchAgents`, starts that same watchdog parent with `RunAtLoad` and `KeepAlive`, and records separate service metadata, heartbeat, watchdog state, and logs under `.codex-loop/`.

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

- `status --summary` now includes `last_blocker_code` and `last_blocker_reason` when the loop blocks, plus the current task session id when one exists.
- `run --continuous --retry-blocked` is the current fastest path to a long-lived local worker: it wraps the normal run loop, requeues blocked tasks between cycles, and keeps going until completed or a cycle limit is reached.
- `daemon start|status|stop` now runs through a detached watchdog parent, with `.codex-loop/daemon.json`, `.codex-loop/daemon-heartbeat.json`, `.codex-loop/daemon-watchdog.json`, and `.codex-loop/daemon.log`; `status` surfaces dead-process and stale-heartbeat detection plus restart counters and restart policy, while `stop` waits for the watchdog to really exit before deleting metadata.
- `service install|status|uninstall` is the macOS path for real unattended persistence: it installs a `launchd` agent, writes `.codex-loop/service.json`, `.codex-loop/service-heartbeat.json`, `.codex-loop/service-watchdog.json`, and `.codex-loop/service.log`, preserves enough environment for the loop to keep finding the local Codex CLI after terminal sessions end, reports `healthy` plus `missing_heartbeat`, tracks watchdog restart counters and restart policy, and now waits for `launchctl` unload confirmation before cleaning local metadata.
- `daemon` and `service` are now intentionally mutually exclusive for the same project root; starting one while the other is active returns an error instead of risking conflicting writes into `.codex-loop/`.
- `sessions` provides a workspace-scoped inventory of known Codex session ids per task, the latest `prompt/log/run` artifacts for each task, and a `--latest` view for the most recent resumable session seen by the loop.
- `evidence` turns a selected task or latest session into a read-only evidence bundle with selection metadata, status/session snapshots, prompt preview, log tail, parsed run payload, recent task events, and optional `--output` or auto-named `--output-dir` export; directory exports also maintain a snapshot `index.json`.
- `snapshots` reads that directory-level `index.json` back as an operator view, with task filtering, status filtering, blocker-code filtering, sort control via `--sort newest|oldest`, `--latest`, the `--latest-blocked` shortcut for the newest blocked snapshot, ISO time windows via `--since/--until`, raw JSON output, file export via `--output`, auto-named archive export via `--output-dir`, and a `--summary` aggregation over task, status, selection, blocker code, and latest snapshot markers; `--group-by task|status|blocker|selection` narrows that summary to one chosen view, and `--output-dir` now maintains a sibling `manifest.json` for exported query results.
- `snapshots-exports` reads that archive `manifest.json` back as a read-only inventory of saved snapshot queries, supports nested task/status/blocker filters plus `--latest` and `--limit`, can render `--summary` views grouped by task, status, blocker, render format, or summary/list shape, and now supports `--output` plus auto-named `--output-dir` exports with a directory-level `index.json`.
- `events --summary` aggregates the filtered event set by label, task, source, blocker code, blocked task, latest blocked event, latest runner failure, and latest verification failure before optional JSON/export handling.
- `events --limit N` merges `.codex-loop/state.json` history with hook execution logs into a readable timeline, and supports `--task-id`, `--event-type`, `--since`, `--until`, `--json`, and `--output` for focused inspection or export.
- `cleanup` defaults to dry-run mode so operators can review what would be deleted before using `--apply`; its default retention policy now comes from `codex-loop.yaml`, and CLI flags such as `--keep`, `--older-than-days`, `--logs-keep`, or `--prompts-older-than-days` override config values per run.
- `.codex-loop/metrics.json` includes blocker aggregates keyed by blocker code.
- `doctor --repair` can backfill missing `operator` defaults into older projects so new CLI behavior does not depend on a manual config rewrite.
- `doctor` also warns when `operator.cleanup` defaults are configured with `keep=0` and no age threshold, which would make `cleanup --apply` destructive by default, and suggests safer retention values to restore.

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
