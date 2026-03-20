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
3. **OpenAI API key** — set it in your shell before running any commands:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```
   To make it permanent, add that line to your `~/.zshrc` or `~/.bashrc`.
4. **A local Git repository with at least one commit** — run `git init && git commit --allow-empty -m 'init'` if starting fresh
5. **Project directory trusted by Codex** — without this, `codex exec` will immediately fail with
   "Not inside a trusted directory". Trust it once by running `codex` inside the directory
   (accept the trust prompt, then Ctrl-C to exit), or add manually to `~/.codex/config.toml`:
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

The minimum path to get started. Run these inside **your own project directory** (not inside the `codex-loop-skill` repo you just cloned):

```bash
# Move into your own project first (must be a Git repo with your code in it)
cd /path/to/your-project

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
    state.json          # loop state (task status, history, blockers)
    metrics.json        # counters and blocker aggregates
    agent_result.schema.json
    logs/               # per-iteration Codex JSONL output
    runs/               # per-task last result JSON
    artifacts/          # snapshots and exports
```

## Task File Format

Each file in `tasks/` is a Markdown document. The filename determines execution order (`001-`, `002-`, ...). The content is passed directly to Codex as the task description.

To declare that a task depends on another:

```markdown
<!-- depends_on: 001-foundation -->
```

The loop skips a task until all its dependencies are `done`. `codex-loop init` generates these automatically from your prompt.

## How Run Works

1. Load `codex-loop.yaml` and auto-repair any state drift
2. Pick the next pending task from `tasks/` (in filename order)
3. Create or reuse a temporary Git worktree so your main branch stays clean
4. Run `codex exec` on that task
5. Run every command in `verification.commands`
6. If verification passes and the task is done, move to the next task
7. If something fails, update failure counters and retry or block based on thresholds
8. Record everything to `.codex-loop/` for later inspection
9. Repeat until all tasks are done or a blocking threshold is reached

For longer unattended runs, add `--continuous --retry-blocked`: when a cycle blocks, it requeues blocked tasks and starts the next cycle until completion or `--max-cycles`.

For background execution, use `daemon start` (watchdog process) or `service install` (macOS launchd, survives reboots). See the Command Reference table above.

## Verification Model

The loop only stops with success when:

- every task is `done`
- all verification commands pass

The loop stops with `blocked` when:

- Codex itself reports it is blocked
- Too many consecutive `codex exec` failures (runner circuit breaker)
- Too many consecutive failed verification runs, if enabled
- Total iteration limit is reached
- No file changes detected across too many iterations (no-progress limit)
- `doctor` finds unrecoverable local state or task file problems

All thresholds are configurable in `codex-loop.yaml` under `execution`.

## Safety Model

- The generated config targets `sandbox_mode="workspace-write"`
- The runner requests `approval_policy="never"` through Codex config overrides
- The supervisor keeps `.codex-loop/` local state outside normal task files
- The supervisor can repair a missing schema and task/state drift before entering the loop
- Hook execution is local and explicit through `codex-loop.yaml`; never inferred from prompts
- The default finish mode is conservative: keep the worktree and branch after completion

## Operator Notes

- `health` gives the fastest single-command overview: it combines status, doctor warnings, event signals, and daemon/service state into one report. Exit code `0=ok`, `2=degraded`, `3=error` — probe-friendly.
- `status --summary` shows the current task, blocker code, and blocker reason when the loop stops.
- `doctor --repair` backfills missing config defaults and reconciles task/state drift. Run it after editing files manually.
- `cleanup` defaults to dry-run. Use `--apply` only after reviewing what would be deleted.
- Artifact retention is configured in `codex-loop.yaml` under `operator.cleanup`. Per-directory overrides (`logs-keep`, `prompts-older-than-days`) can be passed as CLI flags.
- `daemon` and `service` are mutually exclusive for the same project root.

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

To fix the test command, edit `verification.commands` in `codex-loop.yaml`:

```json
"verification": {
  "commands": [
    "python -m pytest tests/ -q"
  ]
}
```

Common examples:
- Python pytest: `python -m pytest tests/ -q`
- Node.js: `npm test`
- Go: `go test ./...`
- Custom script: `bash scripts/verify.sh`

After editing, run `codex-loop doctor --repair` then `codex-loop run --retry-blocked`.

### I edited task files or `codex-loop.yaml` manually

Run `codex-loop doctor --repair` to reconcile state before the next run.

## Known Limits

- The generated `codex-loop.yaml` is JSON-compatible YAML. It works today without a YAML dependency, but full YAML editing is only supported when `PyYAML` is installed.
- Codex CLI approval behavior can vary by CLI version. This project asks for `approval_policy="never"`, but some Codex releases have known approval edge cases.
- Some Codex resume failures are only detectable from CLI error text, so session fallback is heuristic rather than protocol-level.
- Task execution is sequential in the first version. There is no parallel task scheduler yet.

## Skill

This repository also ships a Codex skill at `skills/codex-loop/SKILL.md`. The skill teaches Codex when and how to use `codex-loop` — so instead of running CLI commands yourself, you can just describe your goal to Codex and it will call `codex-loop init`, review the output, and start the loop for you.

To use it, copy or symlink `skills/codex-loop/` into your Codex skills directory (usually `~/.codex/skills/`). Codex will pick it up automatically on the next run.

## Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Compile check:

```bash
python3 -m compileall src
```
