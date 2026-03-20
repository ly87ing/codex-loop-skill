# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Install
```bash
python3 -m pip install -e .
```

### Run tests
```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

### Run a single test file
```bash
PYTHONPATH=src python3 -m unittest tests/test_supervisor.py
```

### Run a single test case
```bash
PYTHONPATH=src python3 -m unittest tests.test_supervisor.TestSupervisor.test_run_completes
```

### Compile check (no test runner needed)
```bash
python3 -m compileall src
```

## Architecture

This is a Python CLI tool (`codex-loop`) that acts as an external supervisor for Codex CLI, enabling autonomous multi-iteration implementation workflows. It also ships a Codex skill at `skills/codex-loop/SKILL.md`.

### Entry points

- **`src/codex_loop/cli.py`** — the entire CLI. All subcommands (`init`, `run`, `status`, `doctor`, `daemon`, `service`, `snapshots`, `events`, `cleanup`, `logs`) are implemented here as a single `main()` function with `argparse`.
- **`pyproject.toml`** — declares the `codex-loop` console script pointing to `codex_loop.cli:main`.

### Core modules

| Module | Role |
|---|---|
| `config.py` | Dataclass config hierarchy loaded from `codex-loop.yaml`. Falls back to JSON if PyYAML is absent. |
| `state_store.py` | Reads/writes `.codex-loop/state.json` — the single source of truth for task status, blocker records, and loop metadata. |
| `task_graph.py` | Parses `tasks/*.md` files, tracks task status and dependencies. |
| `supervisor.py` | Core iteration loop: selects next task → runs Codex → verifies → handles circuit breakers → fires hooks. Returns `LoopOutcome.COMPLETED` or `LoopOutcome.BLOCKED`. |
| `codex_runner.py` | Wraps `codex exec` / `codex exec resume` subprocess calls, handles session resume fallback. |
| `verifier.py` | Runs verification commands from config after each iteration. |
| `hooks.py` | Executes `pre_iteration`, `post_iteration`, `on_completed`, `on_blocked` shell hooks with env vars. |
| `run_flow.py` | Orchestrates a full run: acquires lock, creates worktree, runs doctor, instantiates Supervisor, tears down. |
| `init_flow.py` | Scaffolds `codex-loop.yaml`, `spec/`, `plan/`, `tasks/`, `.codex-loop/state.json` from a prompt. |
| `doctor.py` | Validates and optionally repairs project state (backfills config defaults, checks task/state consistency). |
| `daemon_manager.py` | Manages a detached watchdog process around `run --continuous`. Uses `.codex-loop/daemon.json` and heartbeat files. |
| `service_manager.py` | Installs/uninstalls a macOS `launchd` agent under `~/Library/LaunchAgents`. |
| `reporting.py` | Formats all reporting output: status, snapshots, events, health, session inventory. |
| `cleanup.py` | Prunes artifact directories (`logs/`, `runs/`, `prompts/`) by count or age. |
| `metrics.py` | Accumulates loop metrics (iteration counts, blocker codes, watchdog restarts). |
| `watchdog_manager.py` | Restart-policy logic for the daemon watchdog. |
| `run_lock.py` | File-based lock to prevent concurrent runs against the same project dir. |
| `git_ops.py` | Creates/removes temporary worktrees for isolated execution. |

### Data flow

```
cli.py
  └─ run_flow.py          # acquires lock, worktree, calls doctor
       └─ supervisor.py   # iteration loop
            ├─ task_graph.py    # selects next task
            ├─ codex_runner.py  # calls `codex exec`
            ├─ verifier.py     # runs verification commands
            └─ hooks.py        # fires lifecycle hooks
```

All persistent state lives under `.codex-loop/` in the project directory. Task definitions live in `tasks/*.md`. Configuration lives in `codex-loop.yaml`.

### Circuit breakers

The supervisor stops with `BLOCKED` when any of these thresholds are hit:
- `max_iterations` — total iterations
- `max_no_progress_iterations` — iterations with no task status change (measured by real git diff, not agent self-report)
- `max_consecutive_runner_failures` — consecutive Codex exec failures
- `max_consecutive_verification_failures` — consecutive verification failures

### Reliability invariants

Several design invariants enforce correctness for unattended runs:

- **Real diff over self-report**: `Supervisor._real_files_changed()` uses `git diff --name-only HEAD` to measure actual file changes. The agent-reported `files_changed` field is only used as a fallback when git is unavailable. This prevents Codex from resetting the no-progress counter by lying about changes.
- **Verification-gated completion**: When all tasks self-report `done`, the supervisor runs a final verification pass before declaring `COMPLETED`. If verification fails, the last task is reopened and the loop continues.
- **Verification output in prompt**: The last failed verification's stdout/stderr (up to 1500 chars each) is injected into the next iteration's prompt under `## Last Verification Output (FAILED)`, giving Codex precise error context.
- **Verification timeout**: `VerificationConfig.timeout_seconds` (default 300) is enforced per command via `subprocess.run(timeout=...)`. Timed-out commands are recorded with `timed_out: True` and count as failures.
- **Iteration heartbeat thread**: When `heartbeat_path` is provided, `run_flow._run_supervisor_with_heartbeat()` starts a daemon thread that writes the heartbeat every 60 seconds throughout `supervisor.run()`. This prevents the watchdog (stale threshold: 300 s) from misreading a long `codex exec` call (up to 1800 s) as a dead process.
- **Worktree persistence**: `worktree_path` and `worktree_branch` are stored in `state.json` meta. Subsequent `run_project()` calls reuse the same worktree branch instead of creating a new one, preserving code changes across `--retry-blocked` cycles.
- **Transient error classification**: `Supervisor._is_transient_runner_error()` detects network timeouts, rate limits, and kill signals. Transient errors get backoff-and-retry without incrementing `consecutive_runner_failures` or `consecutive_task_failures`.
- **Task-level circuit breaker**: When a single task fails `max_consecutive_task_failures` times (default 5) consecutively, it is marked `blocked` and the loop continues to the next task instead of halting the entire run.
- **Task dependencies**: Task markdown files can declare `<!-- depends_on: 001-foo, 002-bar -->` (HTML comment anywhere) or `depends_on:` in YAML frontmatter. `_select_task()` skips any task whose dependencies are not yet `done`.

### New config fields (added after initial release)

- `execution.max_consecutive_task_failures` (default 5): task-level circuit breaker threshold. When a single task fails this many times consecutively (runner or verification failures), it is marked `blocked` and skipped; the next pending task is promoted to `ready` and the loop continues.
- `execution.max_consecutive_task_failures = 0`: disables the task-level circuit breaker.
- `verification.timeout_seconds` (default 300): per-command timeout for verification commands. Timed-out commands are recorded with `timed_out: true` and count as failures.

### Skill

`skills/codex-loop/SKILL.md` is a Codex skill definition. Reference docs are in `skills/codex-loop/references/`. This is separate from the Python implementation and describes when/how Codex itself should invoke `codex-loop`.
