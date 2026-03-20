---
name: codex-loop
description: Use when a local coding task is large enough to need a file-driven autonomous loop, especially when the user wants Codex to keep working until verification passes or the task becomes genuinely blocked.
---

# Codex Loop

## Overview

`codex-loop` gives Codex an external supervisor for long local implementation tasks. It turns a prompt into local `spec/plan/tasks` files, then runs Codex iteratively with verification gates and persistent state.

## When To Use

- The user wants Codex to keep working without manual steering.
- The task is bigger than a single prompt-response loop.
- You need durable local state, resumable sessions, or a task queue.
- You want `init --prompt` to scaffold a Ralph-style local workflow.

Do not use this skill for:

- Small one-shot edits
- Pure brainstorming without implementation
- Remote GitHub issue/PR automation

## Workflow

### 1. Initialize local loop files

Run:

```bash
codex-loop init --prompt "<user goal>"
```

This generates `codex-loop.yaml`, `spec/`, `plan/`, `tasks/`, and `.codex-loop/state.json`.

### 2. Review generated files before long execution

- Sanity check the generated spec and task breakdown.
- Tighten verification commands in `codex-loop.yaml` if the defaults are weak.
- Remove obviously unnecessary tasks before starting the loop.

### 3. Repair local drift before the long run

Run:

```bash
codex-loop doctor --repair
```

Use this when task files or local state may have changed since `init`.

### 4. Start the supervisor

Run:

```bash
codex-loop run
```

The supervisor will keep iterating until all tasks are done and verification passes, or until it reaches a real block such as no progress or max iterations.

For longer unattended runs, `codex-loop run --continuous --retry-blocked --cycle-sleep-seconds 60` adds an outer retry loop around the normal supervisor run. When a cycle blocks, it requeues blocked tasks, sleeps, and starts the next cycle until completion or `--max-cycles` is reached.

For a detached local worker, `codex-loop daemon start --retry-blocked --cycle-sleep-seconds 60` now launches a watchdog parent in the background, records daemon metadata plus heartbeat and watchdog state under `.codex-loop/`, and automatically restarts the real worker if it exits unexpectedly or stops updating its heartbeat.

For a real macOS login service, `codex-loop service install --retry-blocked --cycle-sleep-seconds 60` installs a `launchd` agent under `~/Library/LaunchAgents`, records service metadata plus separate heartbeat and watchdog files under `.codex-loop/`, and keeps the loop alive across terminal exits and future logins.

### 5. Inspect status when needed

Run:

```bash
codex-loop status --summary
codex-loop service status --json
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

`status --summary` now includes key runtime counters from `.codex-loop/metrics.json`.
`health` is the one-command operator overview: it combines current status, doctor warnings/errors, event health signals, daemon/service runtime state, and any available snapshot/export summaries.
Its exit code is probe-friendly: `0=ok`, `2=degraded`, `3=error`.
When blocked, it also surfaces the latest `blocker_code` and reason, and when a task has an active session it shows that too. It now also surfaces watchdog exhaustion and the latest watchdog restart reason.
`run --continuous --retry-blocked` is the fastest current path to a long-lived local worker: it wraps the normal run loop, requeues blocked tasks between cycles, and keeps going until completion or a configured cycle limit.
`daemon start|status|stop` now runs through a lightweight detached watchdog layer on top of `run --continuous`, with `.codex-loop/daemon.json`, `.codex-loop/daemon-heartbeat.json`, `.codex-loop/daemon-watchdog.json`, and `.codex-loop/daemon.log` for local operator visibility, plus dead-process and stale-heartbeat detection, restart counters, restart policy, and a stop path that waits for the watchdog to really exit before clearing metadata.
`daemon restart` is the direct operator shortcut for a stop-then-start cycle when you want to bounce the detached worker without typing two commands.
`service install|status|uninstall` is the macOS path for longer unattended persistence: it installs a `launchd` agent, writes `.codex-loop/service.json`, `.codex-loop/service-heartbeat.json`, `.codex-loop/service-watchdog.json`, and `.codex-loop/service.log`, preserves enough environment for the loop to keep finding Codex after shell sessions end, and now surfaces `healthy`, `missing_heartbeat`, watchdog restart counters, restart policy, and uninstall confirmation instead of deleting metadata immediately after `bootout`.
`service reinstall` is the operator shortcut for refreshing the launchd registration and watchdog configuration in one step.
`daemon` and `service` are now mutually exclusive for the same project root; trying to start one while the other is active fails fast instead of risking two long-lived writers against the same `.codex-loop/` state.
`sessions` gives a workspace-scoped inventory of known task session ids, their latest prompt/log/run artifacts, and a `--latest` shortcut for the most recent session seen by the loop.
`evidence` gives a read-only prompt/log/run bundle for the current task, a selected task, or the latest session, embeds bounded task event snapshots plus recent watchdog lifecycle events and status/session metadata, and can export that bundle to disk or an auto-named snapshot directory with an index file.
`snapshots` reads that index file back as a filtered list or JSON payload, supports status, blocker-code, watchdog-phase, time-window, newest/oldest sort control, and a `--latest-blocked` shortcut, can export the rendered result with `--output` or auto-name it with `--output-dir`, and `--summary` turns it into a grouped operator view across task, status, selection, blocker code, watchdog phase, and latest snapshot markers; `--group-by` focuses that summary onto one chosen dimension, and `--output-dir` writes a `manifest.json` alongside the exported files.
`snapshots-exports` reads that archive `manifest.json` back as a read-only inventory of saved snapshot queries, supports task/status/blocker/watchdog-phase filters plus `--latest` and `--limit`, can render `--summary` views grouped by task, status, blocker, render format, or summary/list shape, and can export those filtered views via `--output` or auto-named `--output-dir` archives with an `index.json`.
`events` merges loop history with hook logs, can summarize the filtered set including blocker breakdowns plus the latest runner, verification, and watchdog lifecycle failures, and can export structured JSON to a file.
`cleanup` defaults to dry-run and can combine config-driven retention, count-based limits, age thresholds, and per-directory overrides.
`doctor --repair` can backfill missing operator defaults into older loop configs, and `doctor` warnings now suggest safer cleanup settings when defaults are destructive.

## Key Rules

- The project directory must be trusted by Codex before running. Add it via `codex` interactively or set `trust_level = "trusted"` under `[projects."<absolute-path>"]` in `~/.codex/config.toml`. Without this, `codex exec` will fail immediately with "Not inside a trusted directory".
- Treat generated files as the persistent source of truth, not the original prompt.
- Strengthen `verification.commands` before trusting unattended execution.
- Prefer fixing bad task decomposition at `init` time instead of hoping the loop self-corrects.
- Use `doctor --repair` before reruns if tasks or state have been edited manually.
- Keep hooks local and explicit in `codex-loop.yaml`; do not hide operational behavior in prompts alone.
- Use hook `failure_policy=block` only for operational checks that should genuinely stop the loop.
- If the loop reports `blocked`, inspect the blocker instead of retrying blindly.

## References

- Config details: `references/config.md`
- Loop behavior: `references/workflow.md`
- Safety and operational boundaries: `references/safety.md`
