# codex-loop

`codex-loop` is an external supervisor for [Codex CLI](https://github.com/openai/codex) (OpenAI's terminal coding agent). You give it a goal; it scaffolds
a local task queue, then keeps running Codex — one task at a time — until your tests
pass or the loop hits a real blocker.

**Typical use:** you have a coding task too big for a single prompt. You want Codex
to keep working on it while you do something else, and stop only when it is actually done.

**Not a good fit for:** quick one-off edits, questions, or tasks with no clear pass/fail test.
For those, just use Codex directly.

## How It Works (in brief)

1. `codex-loop init --prompt "..."` — turns your goal into local files: a spec, a plan,
   numbered task documents, and a config (`codex-loop.yaml`).
2. `codex-loop run` — works through each task in order, running Codex and your
   verification commands after every iteration. Stops when everything passes, or
   when it is genuinely stuck.
3. `codex-loop status --summary` — shows you what happened at any time.

All state lives on disk in your project directory, so runs are resumable and inspectable.

```
$ codex-loop run
[iteration 1/30] task: 001-add-validation  (0/2 done, running Codex...) [10:15:02]
  -> status=continue verification=FAIL files_changed=3
[iteration 2/30] task: 001-add-validation  (0/2 done, running Codex...) [10:31:18]
  -> status=complete verification=pass files_changed=2
[iteration 3/30] task: 002-write-tests  (1/2 done, running Codex...) [10:47:55]
  -> status=complete verification=pass files_changed=4
All tasks done and verification passed.
completed
Changes are on branch: codex-loop/my-project-a1b2c3
(Your working directory is unchanged until you merge.)
To merge:
  git checkout main
  git merge codex-loop/my-project-a1b2c3
```

**Ready to start?** → [Prerequisites](#prerequisites) → [Install](#install) → [Quick Start](#quick-start).

## Prerequisites

**Platform:** macOS and Linux. Windows is not supported (requires Git worktrees and Unix process management). The `service` subcommand is macOS-only (launchd); all other commands work on Linux too.

Before installing `codex-loop`, make sure you have:

1. **Python 3.11+** — check with `python3 --version`
2. **[Codex CLI](https://github.com/openai/codex)** installed and working — install via npm or Homebrew:
   ```bash
   npm install -g @openai/codex
   # or
   brew install --cask codex
   ```
   Verify: `codex --version`
3. **OpenAI API key** — set it in your shell before running any commands:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```
   To make it permanent, add that line to your `~/.zshrc` or `~/.bashrc`.
   **Cost:** each iteration calls Codex with a large prompt and expects a structured response. A typical small task (3–10 iterations) costs roughly $0.10–$1.00 depending on the model and codebase size. Set a spending limit on your OpenAI account before running long unattended loops.
4. **A local Git repository with at least one commit** — if starting fresh: `git init && git add -A && git commit -m 'init'`
   (After running `codex-loop init`, the `.codex-loop/` directory is automatically added to `.gitignore` — do not commit it.)
5. **Project directory trusted by Codex** — without this, `codex exec` will immediately fail with
   "Not inside a trusted directory". Trust it once by running `codex` interactively inside your
   project directory, typing something like `hello`, pressing Enter, accepting the trust prompt
   (type `y` or follow on-screen instructions), then pressing Ctrl-C to exit. You only need to
   do this once per directory. Or add it manually to `~/.codex/config.toml`:
   ```toml
   [projects."<absolute-path-to-your-project>"]
   trust_level = "trusted"
   ```

## Install

`codex-loop` has no third-party Python dependencies — just Python 3.11+ and the tools you already have.

```bash
git clone https://github.com/ly87ing/codex-loop-skill.git
cd codex-loop-skill
python3 -m pip install -e .
cd ..   # go back — next, cd into YOUR project directory (not this one)
```

> **Note:** `-e` (editable install) means the `codex-loop-skill` directory must stay where it is — do not move or delete it after installing.

> **Tip:** if you use virtual environments and want `codex-loop` available everywhere without activating one,
> install with `pipx` instead: `pipx install -e ./codex-loop-skill`
> (pipx also puts `codex-loop` on your PATH automatically, which avoids the `command not found` issue)

Verify it worked:

```bash
codex-loop --help
# If you get 'command not found', see Troubleshooting below.
```

## Quick Start

The minimum path to get started. Run these inside **your own project directory** (not inside the `codex-loop-skill` repo you just cloned):

```bash
# Move into your own project first (must be a Git repo with at least one commit)
cd /path/to/your-project

# 0. One-time setup — if you haven't done these yet:
#    a) Git repo with a commit:  git init && git add -A && git commit -m "init"
#    b) Trust in Codex (one-time, per directory) — skip this and you'll get
#       "Not inside a trusted directory" when you run step 3:
#         Run: codex
#         Then type "hello", press Enter, accept the trust prompt (type y), then Ctrl-C.

# 1. Scaffold workflow files from your goal
#    A good prompt names the language/framework, what to build, and how to test it.
#    Examples:
#      "Add input validation to every form in this app (Python/Flask). Tests in pytest."
#      "Implement a REST API endpoint for user registration (Node/Express). Tests in jest."
#      "Refactor the database layer to use SQLAlchemy. Tests in pytest."
codex-loop init --prompt "Add input validation to every form in this app"
# (This calls Codex to generate your project files — usually takes 30–90 seconds.)

# 2. Review generated files — especially the verification command
#    Open codex-loop.yaml in your editor and confirm verification.commands matches
#    how you actually run your tests (this is the most important field):
cat codex-loop.yaml
#    Example — if your project uses pytest:
#      "verification": { "commands": ["python -m pytest tests/ -q"] }
#    Tip: run that command manually now to confirm it works before starting the loop.
#    Note: codex-loop.yaml uses JSON syntax (not indented YAML) — that is normal.
#    Do NOT change execution.sandbox or execution.approval — required for unattended runs.
#    Also skim spec/, plan/, and tasks/ to make sure the goal was captured correctly.
#    If the output looks wrong, re-run with a better prompt:
#      codex-loop init --prompt "..." --force

# 3. Run the loop — it will keep working until done or genuinely blocked
#    Each iteration calls Codex and waits up to 30 minutes for a response.
#    A typical small task takes 3–10 iterations (15 minutes to a few hours).
#    Each iteration shows one progress line before Codex starts, then goes quiet
#    while Codex works (up to 30 min per iteration) — silence during that gap is normal.
#    A result line is printed after each iteration completes.
#    To see a human-readable timeline at any time, open another terminal and run:
#      codex-loop events --limit 10
#    (For raw Codex output: codex-loop logs tail --lines 50)
#    You can press Ctrl-C at any time to stop safely; the next run picks up where it left off.
codex-loop run
# You will see output like:
#   [iteration 1/30] task: 001-foundation  (0/2 done, running Codex...) [14:23:01]
#     -> status=continue verification=FAIL files_changed=3
#        ("continue" = Codex is still working on it; "FAIL" = tests not passing yet — this is normal)
#   [iteration 2/30] task: 001-foundation  (0/2 done, running Codex...) [14:31:45]
#     -> status=complete verification=FAIL files_changed=2
#        ("complete" = Codex thinks it's done, but tests still fail — loop keeps going automatically)
#   [iteration 3/30] task: 001-foundation  (0/2 done, running Codex...) [14:39:12]
#     -> status=complete verification=pass files_changed=3
#        ("complete" + "pass" = task verified done; loop moves to next task)
#   All tasks done and verification passed.
#   completed
#   Changes are on branch: codex-loop/my-project-abc123
#   To inspect before merging:
#     git diff --stat main..codex-loop/my-project-abc123
#   To merge:
#     git checkout main
#     git merge codex-loop/my-project-abc123
#   After merging, clean up with: codex-loop cleanup --apply

# Note: Codex writes all changes to an isolated Git branch, not your project directory.
#       You won't see any changed files locally until you merge in step 4.

# 4. Merge the changes
#    When the loop completes, it prints the exact commands to run. Copy and run them:
#      git checkout main   # or master, or your default branch
#      git merge codex-loop/<branch>   # use the branch name printed above
#    If you need to find the branch name later:
#      git branch | grep codex-loop
#    After merging, clean up old log/run artifacts (does NOT delete your code or git history):
codex-loop cleanup --apply

# 5. Check status at any time
codex-loop status --summary
```

Example output:

```
project: my-project
overall_status: running          # running | completed | blocked
iteration: 3
tasks:
  [x] 001-create-schema  (done)
  [~] 002-add-api        (in_progress)
  [ ] 003-write-tests    (ready)
current_task: 002-add-api
worktree_branch: codex-loop/my-project-abc123
```

Task markers: `[x]` done, `[~]` in progress, `[!]` blocked, `[ ]` pending.
If `overall_status` is `blocked`, the loop stopped — run `codex-loop run --retry-blocked` to retry.

That is all you need for most tasks. The loop stops by itself when all tasks pass verification,
or when it hits a real blocker (no progress, too many failures).

### Example

See [`examples/simple-local-project/`](examples/simple-local-project/) for a worked example
showing what `codex-loop init` generates for a real goal (a Python todo CLI), with realistic
spec, plan, tasks, and config files you can copy as a starting point.

That directory includes step-by-step instructions in its README — it is the fastest way to see
a complete end-to-end run without setting up your own project first.

### After the loop completes

The loop runs Codex in an isolated Git branch (prefix: `codex-loop/`). When it finishes,
`codex-loop run` prints the exact merge command to use:

```
completed
Changes are on branch: codex-loop/my-project-abc123
To inspect before merging:
  git diff --stat main..codex-loop/my-project-abc123
To merge:
  git checkout main   # or master, or your default branch
  git merge codex-loop/my-project-abc123
After merging, clean up with: codex-loop cleanup --apply
```

Copy that `git merge` command and run it in your project directory (make sure you are on your main branch first). Or inspect first:

```bash
# Make sure you're on your main branch
git checkout main   # or master, or whatever your default branch is

# See which files were changed
git diff --stat main..codex-loop/my-project-abc123

# See the full diff
git diff main..codex-loop/my-project-abc123

# See the commit history
git log main..codex-loop/my-project-abc123 --oneline

# Then merge
git merge codex-loop/my-project-abc123
```

If you need to find the branch name later:

```bash
git branch | grep codex-loop
# or
codex-loop status --summary   # shows worktree_branch
```

The changes live in an isolated Git branch (`codex-loop/...`). Use `git diff` and `git log` (shown above) to review — you don't need to navigate to any worktree directory. After merging, clean up with:

```bash
codex-loop cleanup --apply
# This removes the worktree directory and prunes old logs under .codex-loop/.
# It does NOT touch your source code, your main branch, or the merged changes.
```

If you inspect the changes and decide you don't want them, simply don't merge.
The branch and worktree stay in place until you clean them up.
To discard everything and start fresh:

```bash
codex-loop cleanup --apply   # removes worktrees and old artifacts
codex-loop init --prompt "..." --force   # re-scaffold (WARNING: resets all state)
```

### Running a new goal on the same project

After merging and cleaning up, you can start a new loop on the same project:

```bash
codex-loop cleanup --apply   # clean up old worktrees and artifacts first
codex-loop init --prompt "your next goal" --force   # re-scaffold with new goal
codex-loop run
```

`--force` is required because `codex-loop.yaml` and the task files already exist. It will replace them with a fresh scaffold for the new goal.

### If the loop blocks

When the loop stops with `blocked`, the reason is printed directly in the terminal:

```
blocked
Blocked: [no_progress_limit] No file changes detected for 4 consecutive iterations.
Run 'codex-loop status --summary' for full details.
To retry: codex-loop run --retry-blocked
```

For more detail:

```bash
codex-loop status --summary   # current task, blocker code, blocker reason
codex-loop events --limit 20  # full event timeline with verification output
```

After fixing the root cause, retry:

```bash
# Retry once
codex-loop run --retry-blocked

# Or keep retrying automatically
codex-loop run --continuous --retry-blocked --cycle-sleep-seconds 60
```

### Unattended long runs (optional)

Use `daemon` (or `service` on macOS) when you want the loop to run in the background and survive terminal closes. Use `run --continuous` if you want to keep the terminal attached and watch the output.

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

## Command Reference

For most tasks, you only need three commands: `init`, `run`, and `status --summary`.
The rest are for inspection, long-running unattended jobs, or cleanup.

| Command | What it does |
|---|---|
| `init --prompt "..."` | Scaffold spec, plan, tasks, and config from your goal. Add `--model <name>` to override the Codex model used for init (default: `gpt-5.4`). |
| `run` | Run the loop until done or blocked (exits 0 on success, 2 if blocked) |
| `run --retry-blocked` | Requeue blocked tasks then run |
| `run --continuous --retry-blocked` | Keep retrying after blocks until `--max-cycles` |
| `doctor --repair` | Fix state drift if you edited files manually |
| `health` | One-command overview: status, warnings, events, daemon state |
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

## Why This Exists

Codex handles individual prompts well, but longer tasks need:

- durable state across iterations (a single prompt drifts and forgets)
- verification gates (the loop only calls something done when tests actually pass)
- unattended execution (no interactive approval prompts mid-run)
- a structured way to see what happened when something went wrong

## Generated Project Layout

```text
your-project/
  codex-loop.yaml         # commit this — it's your project config
  spec/                   # commit these — they're your project docs
    001-project-spec.md
  plan/
    001-implementation-plan.md
  tasks/
    001-*.md
  .codex-loop/            # do NOT commit — codex-loop init automatically adds this
                          # to both .gitignore and .git/info/exclude
    state.json            # loop state (task status, history, blockers)
    metrics.json          # counters and blocker aggregates
    agent_result.schema.json
    logs/                 # per-iteration Codex output (one JSON object per line)
    runs/                 # per-task last result JSON
    artifacts/            # snapshots and exports

# Codex runs in an isolated worktree (you never need to navigate here):
# ../.codex-loop-worktrees/<repo>/<branch>/
```

## Task File Format

Each file in `tasks/` is a Markdown document. The filename determines execution order (`001-`, `002-`, ...). The content is passed directly to Codex as the task description.

To declare that a task depends on another:

```markdown
<!-- depends_on: 001-foundation -->
```

The loop skips a task until all its dependencies are `done`. `codex-loop init` generates these automatically from your prompt.

You can edit task files freely before or between runs to tighten the description, split a task, or remove tasks you don't need. After editing, run `codex-loop doctor --repair` to sync the state file.

## Hooks (optional)

Hooks let you run shell commands at key points in the loop. Configure them in `codex-loop.yaml`:

```json
"hooks": {
  "pre_iteration": ["cp .env $CODEX_LOOP_WORKING_DIR/"],
  "post_iteration": [],
  "on_completed": ["bash scripts/notify.sh"],
  "on_blocked": []
}
```

Available events:

| Event | When it runs |
|---|---|
| `pre_iteration` | Before each Codex call |
| `post_iteration` | After verification completes |
| `on_completed` | When the loop finishes successfully |
| `on_blocked` | When the loop stops due to a blocker |

Environment variables available in every hook:

| Variable | Value |
|---|---|
| `CODEX_LOOP_PROJECT_DIR` | Absolute path to your project directory |
| `CODEX_LOOP_WORKING_DIR` | Absolute path to the worktree (where Codex is working) |
| `CODEX_LOOP_TASK_ID` | Current task ID (e.g. `001-foundation`) |
| `CODEX_LOOP_TASK_TITLE` | Current task title |
| `CODEX_LOOP_EVENT` | Event name (`pre_iteration`, `on_completed`, etc.) |

Hooks run in the worktree directory. If a hook exits non-zero and `hooks.failure_policy` is `"block"` (default: `"ignore"`), the loop stops.

## How Run Works

1. Load `codex-loop.yaml` and auto-repair any state drift
2. Pick the next pending task from `tasks/` (in filename order)
3. Create or reuse an isolated Git worktree so your main branch stays clean
4. Run `codex exec` on that task
5. Run every command in `verification.commands`
6. If verification passes and the task is done, move to the next task
7. If something fails, update failure counters and retry or block based on thresholds
8. Record everything to `.codex-loop/` for later inspection
9. Repeat until all tasks are done or a blocking threshold is reached

The loop is safe to interrupt with Ctrl-C at any time. State is written after each completed iteration, so a subsequent `codex-loop run` picks up where it left off.

For longer unattended runs, add `--continuous --retry-blocked`: when a cycle blocks, it requeues blocked tasks and starts the next cycle until completion or `--max-cycles`.

For background execution, use `daemon start` (watchdog process) or `service install` (macOS launchd, survives reboots). See the Command Reference table above.

## Verification Model

The loop only stops with success when:

- every task is `done`
- all verification commands pass

The loop stops with `blocked` when:

- Codex itself reports it is blocked
- Too many consecutive `codex exec` failures (runner circuit breaker)
- Too many consecutive failed verification runs, if enabled (`max_consecutive_verification_failures` in `codex-loop.yaml`; default `0` = disabled, loop keeps retrying)
- Total iteration limit is reached
- No file changes detected across too many iterations (no-progress limit)
- `doctor` finds unrecoverable local state or task file problems

All thresholds are configurable in `codex-loop.yaml` under `execution`.

## Safety Model

- `sandbox_mode="workspace-write"` — Codex can read and write files in your project, but cannot access the network or run arbitrary system commands outside the workspace
- `approval_policy="never"` — Codex does not pause for interactive approval, which is required for unattended runs; changes go to an isolated Git branch so you can review before merging
- The supervisor keeps `.codex-loop/` local state outside normal task files
- The supervisor can repair a missing schema and task/state drift before entering the loop
- Hook execution is local and explicit through `codex-loop.yaml`; never inferred from prompts
- The default finish mode is conservative: keep the worktree and branch after completion

## Useful Things to Know

- `health` gives the fastest single-command overview: it combines status, doctor warnings, event signals, and daemon/service state into one report.
- `status --summary` shows the current task, blocker code, and blocker reason when the loop stops.
- `doctor --repair` backfills missing config defaults and reconciles task/state drift. Run it after editing files manually.
- `cleanup` defaults to dry-run (preview only). Use `--apply` only after reviewing what would be deleted.
- `daemon` and `service` are mutually exclusive for the same project root — pick one or the other for background runs.

## Troubleshooting

### `codex-loop: command not found`

The `codex-loop` command is installed by pip into a user scripts directory that may not be on your PATH.

Fix with pipx (recommended — puts it on PATH automatically):

```bash
pipx install -e ./codex-loop-skill
```

Or find where pip installed the script and add that to your PATH:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))"
# Copy the output (e.g. /Users/you/Library/Python/3.11/bin) and add to ~/.zshrc or ~/.bashrc:
#   export PATH="/Users/you/Library/Python/3.11/bin:$PATH"
```

Or run it directly without installing:

```bash
python3 -m codex_loop.cli --help
```

### "Codex could not authenticate" / API key error

Both `codex-loop init` and `codex-loop run` call `codex exec`, which exits immediately if
`OPENAI_API_KEY` is not set or is invalid.

```bash
export OPENAI_API_KEY="sk-..."
```

To make it permanent, add that line to your `~/.zshrc` or `~/.bashrc`.

### "Not inside a trusted directory"

Both `codex-loop init` and `codex-loop run` call `codex exec`, which refuses to run in
directories that Codex has not explicitly trusted.
Fix it once by running `codex` interactively inside your project directory,
or add it manually to `~/.codex/config.toml`:

```toml
[projects."/absolute/path/to/your-project"]
trust_level = "trusted"
```

### "not inside a Git repository"

`codex-loop run` requires a Git repository with at least one commit.
If you see this error, initialize the repository first:

```bash
git init
git add -A
git commit -m "init"
```
(`.codex-loop/` is automatically added to `.gitignore` by `codex-loop init`, so `git add -A` is safe.)

### The loop stops with `blocked`

This is not a crash — it means the loop hit a real limit it could not resolve on its own.
The reason is printed directly in the terminal when the loop exits. For more detail:

```bash
codex-loop status --summary   # task status and blocker reason
codex-loop events --limit 20  # full timeline with verification output
```

Common causes and fixes:

| Blocker | What happened | What to do |
|---|---|---|
| `no_progress_limit` | Codex made no file changes for 5 consecutive iterations (default) | Review the task description; make it more specific |
| `runner_failure_circuit_breaker` | `codex exec` failed repeatedly | Check your API key and network; run `codex` manually to verify |
| `verification_failure_circuit_breaker` | Tests kept failing | Look at `codex-loop events --limit 20` for the error output |
| `task_failure_circuit_breaker` | One task failed too many times; loop continues with next task | Check `codex-loop status --summary` to see which task was skipped |
| `max_iterations` | Hit the iteration cap | Increase `max_iterations` in `codex-loop.yaml` or break the task into smaller pieces |
| `agent_blocked` | Codex reported it is stuck and cannot continue | Edit the relevant task file to give more context, then `codex-loop run --retry-blocked` |
| `no_selectable_task` | All remaining tasks are waiting on dependencies that are not done | Check `codex-loop status --summary`; a dependency task may be blocked and need `--retry-blocked` |

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

To run multiple commands (all must pass):

```json
"verification": {
  "commands": [
    "python -m pytest tests/ -q",
    "python -m mypy src/"
  ]
}
```

Common examples:
- Python pytest: `python -m pytest tests/ -q`
- Node.js: `npm test`
- Go: `go test ./...`
- Custom script: `bash scripts/verify.sh`

If your project uses a virtual environment, use the full path to the interpreter so the command works without activating it first:
- `".venv/bin/python -m pytest tests/ -q"` (Linux/macOS with venv in `.venv/`)
- `"./node_modules/.bin/jest"` (Node.js with local install)

After editing, run `codex-loop doctor --repair` then `codex-loop run --retry-blocked`.

**If your project has no tests yet:** set `verification.commands` to an empty list (`[]`). The loop will run until Codex declares all tasks done, with no pass/fail gate. This is fine for getting started, but without verification the loop cannot tell if the code actually works — add real tests when you can.

### The generated spec, plan, or tasks don't look right

If `codex-loop init` produced tasks that don't match your goal, re-run it with a better prompt:

```bash
codex-loop init --prompt "your more specific goal" --force
```

`--force` overwrites the previous generated files. Tips for a better prompt:
- Name the language and framework explicitly (e.g. "Python/Flask", "Node/Express")
- Name the test tool (e.g. "tests in pytest", "tests in jest")
- Be specific about what to build (e.g. "add input validation to every form" not just "add validation")

### I get a JSON parse error when editing `codex-loop.yaml`

`codex-loop.yaml` uses JSON syntax (curly braces, quoted keys, commas) even though it has a `.yaml` extension. If you accidentally introduced invalid JSON:

```bash
# Check the syntax:
python3 -c "import json; json.load(open('codex-loop.yaml'))"
```

The error message will show the line number. Common mistakes: trailing commas, missing quotes around keys, single quotes instead of double quotes. If the file is beyond repair, re-generate it with:

```bash
codex-loop init --prompt "your goal" --force
```

### How do I see what Codex is actually doing?

While the loop runs, Codex output is captured internally (not shown live) so the supervisor can parse the JSON result.

For a human-readable summary of what happened in recent iterations (recommended):

```bash
codex-loop events --limit 10
```

To see the raw Codex output (one JSON object per line — useful for debugging):

```bash
codex-loop logs tail --lines 50
```

### I edited task files or `codex-loop.yaml` manually

Run `codex-loop doctor --repair` to reconcile state before the next run.

### My tests still fail even after the loop reports `completed`

Codex makes changes in an isolated Git branch, not in your project directory directly.
Your project files are unchanged until you merge. That is why running tests locally shows the old code.

After the loop completes, merge the branch first:

```bash
git checkout main   # or master
git merge codex-loop/<branch>   # use the branch name printed by codex-loop run
```

Then run your tests. They should pass against the merged code.

## Known Limits

- **Untracked files are not in the worktree.** Codex runs in an isolated Git worktree that only contains committed files. If your project needs untracked files to run tests, add a `pre_iteration` hook in `codex-loop.yaml` that sets them up before each iteration:
  ```json
  "hooks": {
    "pre_iteration": [
      "cp /path/to/your-project/.env $CODEX_LOOP_WORKING_DIR/",
      "npm install --prefix $CODEX_LOOP_WORKING_DIR"
    ]
  }
  ```
  Common cases: `.env` files (copy them in), `node_modules/` (run `npm install` rather than copying — it's faster), Python virtualenvs (run `pip install -e .` or `pip install -r requirements.txt` in the worktree). The worktree path is also available as `$CODEX_LOOP_WORKING_DIR` in hooks.
- Each iteration waits up to **30 minutes** for Codex to respond (`iteration_timeout_seconds: 1800` in `codex-loop.yaml`). During this time the terminal shows no output — that is normal. Run `codex-loop events --limit 10` after an iteration completes to see what happened, or reduce `iteration_timeout_seconds` in `codex-loop.yaml` if you need a shorter timeout.
- `codex-loop.yaml` uses JSON syntax (curly braces and quoted keys), not indented YAML. This is intentional — it avoids a PyYAML dependency. You can edit it with any text editor; just keep the JSON structure intact. Install `pip install pyyaml` if you want to use standard YAML indentation syntax instead.
- Codex CLI approval behavior can vary by CLI version. This project asks for `approval_policy="never"`, but some Codex releases have known approval edge cases.
- Some Codex resume failures are only detectable from CLI error text, so session fallback is heuristic rather than protocol-level.
- Task execution is sequential in the first version. There is no parallel task scheduler yet.

## Skill

This repository also ships a Codex skill at `skills/codex-loop/SKILL.md`. The skill teaches Codex when and how to use `codex-loop` — so instead of running CLI commands yourself, you can just describe your goal to Codex and it will call `codex-loop init`, review the output, and start the loop for you.

To use it, run this from inside the `codex-loop-skill` directory you cloned:

```bash
mkdir -p ~/.codex/skills
ln -s "$(pwd)/skills/codex-loop" ~/.codex/skills/codex-loop
```

Codex will pick it up automatically on the next run.

## Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Compile check:

```bash
python3 -m compileall src
```

## Getting Help

If something is not working:

1. Run `codex-loop doctor` — it checks your config, task files, and state file, and prints specific hints for common problems.
2. Run `codex-loop status --summary` — it shows which task is active, what the last blocker was, and how many iterations have run.
3. If still stuck, open an issue at https://github.com/ly87ing/codex-loop-skill/issues with:
   - the command you ran
   - the error message or unexpected output
   - your OS, `codex --version`, and `codex-loop --version`
