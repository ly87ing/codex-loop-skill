# codex-loop

`codex-loop` is an external supervisor for Codex CLI. You give it a goal; it scaffolds
a local task queue, then keeps running Codex — one task at a time — until your tests
pass or the loop hits a real blocker.

**Typical use:** you have a coding task too big for a single prompt. You want Codex
to keep working on it while you do something else, and stop only when it is actually done.

## How It Works (in brief)

1. `codex-loop init --prompt "..."` — turns your goal into local files: a spec, a plan,
   numbered task documents, and a config (`codex-loop.yaml`).
2. `codex-loop run` — works through each task in order, running Codex and your
   verification commands after every iteration. Stops when everything passes, or
   when it is genuinely stuck.
3. `codex-loop status --summary` — shows you what happened at any time.

All state lives on disk in your project directory, so runs are resumable and inspectable.

## Why This Exists

Codex handles individual prompts well, but longer tasks need:

- durable state across iterations (a single prompt drifts and forgets)
- verification gates (the loop only calls something done when tests actually pass)
- unattended execution (no interactive approval prompts mid-run)
- a structured way to see what happened when something went wrong

## Command Reference

| Command | What it does |
|---|---|
| `init --prompt "..."` | Scaffold spec, plan, tasks, and config from your goal |
| `run` | Run the loop until done or blocked |
| `run --continuous --retry-blocked` | Keep retrying after blocks until `--max-cycles` |
| `doctor --repair` | Fix state drift if you edited files manually |
| `status --summary` | Show current task status and loop health |
| `events --limit 20` | Show the recent event timeline |
| `sessions --latest --json` | Show the last Codex session details |
| `logs tail --lines 20` | Tail the loop log |
| `cleanup --keep 10` | Preview artifact pruning (dry-run) |
| `cleanup --apply --keep 10` | Actually prune old artifacts |
| `daemon start` | Run as a background watchdog process |
| `daemon status` | Check watchdog health |
| `daemon stop` | Stop the background watchdog |
| `service install` | Install as a macOS launchd service (survives reboots) |
| `service status` | Check service health |
| `service uninstall` | Remove the launchd service |

## Example

See [`examples/simple-local-project/`](examples/simple-local-project/) for a worked example
showing what `codex-loop init` generates for a real goal (a Python todo CLI), with realistic
spec, plan, tasks, and config files you can copy as a starting point.

## Prerequisites

Before installing `codex-loop`, make sure you have:

1. **Python 3.11+** — check with `python3 --version`
2. **Codex CLI** installed and working — see [github.com/openai/codex](https://github.com/openai/codex)
3. **OpenAI API key** — set `OPENAI_API_KEY` in your shell
4. **A local Git repository** — run `git init` first if needed
5. **Project directory trusted by Codex** — without this, `codex exec` will immediately fail with
   "Not inside a trusted directory". Trust it once interactively by running `codex` inside the
   directory, or add manually to `~/.codex/config.toml`:
   ```toml
   [projects."<absolute-path-to-your-project>"]
   trust_level = "trusted"
   ```

## Install

```bash
git clone https://github.com/ly87ing/codex-loop-skill.git
cd codex-loop-skill
python3 -m pip install -e .
```

Verify it worked:

```bash
codex-loop --help
```

## Quick Start

The minimum path to get started (run these in order inside your Git repository):

```bash
# 1. Scaffold workflow files from your goal
codex-loop init --prompt "Add input validation to every form in this app"

# 2. Review generated files and check the verification command
#    Open codex-loop.yaml and confirm verification.commands matches how you run your tests.
#    Also skim spec/, plan/, and tasks/ to make sure the goal was captured correctly.

# 3. Run the loop — it will keep working until done or genuinely blocked
codex-loop run

# 4. Check status at any time
codex-loop status --summary
```

That is all you need for most tasks. The loop stops by itself when all tasks pass verification,
or when it hits a real blocker (no progress, too many failures).

### If the loop blocks

```bash
# See what happened
codex-loop status --summary
codex-loop events --limit 20

# Retry blocked tasks and keep looping
codex-loop run --continuous --retry-blocked --cycle-sleep-seconds 60
```

### Unattended long runs (optional)

```bash
# Run as a background daemon with auto-restart
codex-loop daemon start --retry-blocked --cycle-sleep-seconds 60
codex-loop daemon status --json
codex-loop daemon stop

# Or install as a macOS launchd service that survives reboots
codex-loop service install --retry-blocked --cycle-sleep-seconds 60
codex-loop service status --json
codex-loop service uninstall
```

### Inspection and cleanup

```bash
codex-loop health
codex-loop sessions --latest --json
codex-loop logs tail --lines 20
codex-loop cleanup --keep 10                          # dry-run preview
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

For longer unattended runs, add `--continuous --retry-blocked`: when a cycle blocks, it requeues blocked tasks and starts the next cycle until completion or `--max-cycles`.

For background execution, use `daemon start` (watchdog process) or `service install` (macOS launchd, survives reboots). See the Command Reference table above.

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
- `status --summary` now also surfaces watchdog exhaustion and the latest watchdog restart reason so an operator can see when unattended recovery has stopped succeeding.
- `health` is the fastest operator overview when you want one answer instead of switching between `status`, `events`, `snapshots`, `doctor`, and daemon/service status; it aggregates those signals into one local summary or JSON payload.
  `health` also acts as a probe now: exit code `0` means `ok`, `2` means `degraded`, and `3` means `error`.
- `run --continuous --retry-blocked` is the current fastest path to a long-lived local worker: it wraps the normal run loop, requeues blocked tasks between cycles, and keeps going until completed or a cycle limit is reached.
- `daemon start|status|stop` now runs through a detached watchdog parent, with `.codex-loop/daemon.json`, `.codex-loop/daemon-heartbeat.json`, `.codex-loop/daemon-watchdog.json`, and `.codex-loop/daemon.log`; `status` surfaces dead-process and stale-heartbeat detection plus restart counters and restart policy, while `stop` waits for the watchdog to really exit before deleting metadata.
- `daemon restart` is the operator shortcut for an explicit stop-then-start cycle without manually sequencing both commands.
- `service install|status|uninstall` is the macOS path for real unattended persistence: it installs a `launchd` agent, writes `.codex-loop/service.json`, `.codex-loop/service-heartbeat.json`, `.codex-loop/service-watchdog.json`, and `.codex-loop/service.log`, preserves enough environment for the loop to keep finding the local Codex CLI after terminal sessions end, reports `healthy` plus `missing_heartbeat`, tracks watchdog restart counters and restart policy, and now waits for `launchctl` unload confirmation before cleaning local metadata.
- `service reinstall` is the operator shortcut for refreshing the launchd registration and watchdog configuration in one step.
- `daemon` and `service` are now intentionally mutually exclusive for the same project root; starting one while the other is active returns an error instead of risking conflicting writes into `.codex-loop/`.
- `doctor` now warns when a daemon or service watchdog is in `exhausted` phase, which means unattended retries have stopped and human intervention is required.
- `sessions` provides a workspace-scoped inventory of known Codex session ids per task, the latest `prompt/log/run` artifacts for each task, and a `--latest` view for the most recent resumable session seen by the loop.
- `evidence` turns a selected task or latest session into a read-only evidence bundle with selection metadata, status/session snapshots, prompt preview, log tail, parsed run payload, recent task events, recent watchdog lifecycle events, and optional `--output` or auto-named `--output-dir` export; directory exports also maintain a snapshot `index.json`.
- `snapshots` reads that directory-level `index.json` back as an operator view, with task filtering, status filtering, blocker-code filtering, watchdog-phase filtering, sort control via `--sort newest|oldest`, `--latest`, the `--latest-blocked` shortcut for the newest blocked snapshot, ISO time windows via `--since/--until`, raw JSON output, file export via `--output`, auto-named archive export via `--output-dir`, and a `--summary` aggregation over task, status, selection, blocker code, watchdog phase, and latest snapshot markers; `--group-by task|status|blocker|selection` narrows that summary to one chosen view, and `--output-dir` now maintains a sibling `manifest.json` for exported query results.
- `snapshots-exports` reads that archive `manifest.json` back as a read-only inventory of saved snapshot queries, supports nested task/status/blocker/watchdog-phase filters plus `--latest` and `--limit`, can render `--summary` views grouped by task, status, blocker, render format, or summary/list shape, and now supports `--output` plus auto-named `--output-dir` exports with a directory-level `index.json`.
- `events --summary` aggregates the filtered event set by label, task, source, blocker code, blocked task, latest blocked event, latest runner failure, latest verification failure, and the latest watchdog restart or exhausted event before optional JSON/export handling.
- `events --limit N` merges `.codex-loop/state.json` history with hook execution logs into a readable timeline, and supports `--task-id`, `--event-type`, `--since`, `--until`, `--json`, and `--output` for focused inspection or export.
- `cleanup` defaults to dry-run mode so operators can review what would be deleted before using `--apply`; its default retention policy now comes from `codex-loop.yaml`, and CLI flags such as `--keep`, `--older-than-days`, `--logs-keep`, or `--prompts-older-than-days` override config values per run.
- `.codex-loop/metrics.json` includes blocker aggregates keyed by blocker code, plus watchdog restart totals, exhaustion totals, restart reasons, and the latest watchdog restart/exhausted payloads.
- `doctor --repair` can backfill missing `operator` defaults into older projects so new CLI behavior does not depend on a manual config rewrite.
- `doctor` also warns when `operator.cleanup` defaults are configured with `keep=0` and no age threshold, which would make `cleanup --apply` destructive by default, and suggests safer retention values to restore.

## Troubleshooting

### "Not inside a trusted directory"

`codex exec` refuses to run in directories that Codex has not explicitly trusted.
Fix it once by running `codex` interactively inside your project directory,
or add it manually to `~/.codex/config.toml`:

```toml
[projects."/absolute/path/to/your-project"]
trust_level = "trusted"
```

### The loop stops with `blocked`

This is not a crash — it means the loop hit a real limit it could not resolve on its own.

```bash
# See the reason
codex-loop status --summary
codex-loop events --limit 20
```

Common causes and fixes:

| Blocker | What happened | What to do |
|---|---|---|
| `no_progress_limit` | Codex made no file changes for N iterations | Review the task description; make it more specific |
| `runner_failure_circuit_breaker` | `codex exec` failed repeatedly | Check your API key and network; run `codex` manually to verify |
| `verification_failure_circuit_breaker` | Tests kept failing | Look at `codex-loop events --limit 20` for the error output |
| `max_iterations` | Hit the iteration cap | Increase `max_iterations` in `codex-loop.yaml` or break the task into smaller pieces |

After fixing the root cause:

```bash
codex-loop run --retry-blocked
```

### Verification keeps failing

The loop injects the last failed verification output into the next prompt automatically.
If it keeps failing, the test command itself may be wrong. Check it manually:

```bash
# Run your verification command directly to see the real error
python -m pytest tests/ -q
```

Then fix either the test command in `codex-loop.yaml` or the task description.

### I edited task files or `codex-loop.yaml` manually

Run `codex-loop doctor --repair` to reconcile state before the next run.

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
