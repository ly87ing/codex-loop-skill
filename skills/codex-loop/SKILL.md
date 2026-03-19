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

### 5. Inspect status when needed

Run:

```bash
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
When blocked, it also surfaces the latest `blocker_code` and reason, and when a task has an active session it shows that too.
`sessions` gives a workspace-scoped inventory of known task session ids, their latest prompt/log/run artifacts, and a `--latest` shortcut for the most recent session seen by the loop.
`evidence` gives a read-only prompt/log/run bundle for the current task, a selected task, or the latest session, embeds bounded task event snapshots plus status/session metadata, and can export that bundle to disk or an auto-named snapshot directory with an index file.
`snapshots` reads that index file back as a filtered list or JSON payload, supports status and time-window filtering, and `--summary` turns it into a grouped operator view across task, status, selection, blocker code, and latest snapshot markers.
`events` merges loop history with hook logs, can summarize the filtered set including blocker breakdowns plus latest runner or verification failures, and can export structured JSON to a file.
`cleanup` defaults to dry-run and can combine config-driven retention, count-based limits, age thresholds, and per-directory overrides.
`doctor --repair` can backfill missing operator defaults into older loop configs, and `doctor` warnings now suggest safer cleanup settings when defaults are destructive.

## Key Rules

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
