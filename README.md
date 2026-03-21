# codex-loop

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green) ![Platform: macOS and Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)

`codex-loop` is an external supervisor for [Codex CLI](https://github.com/openai/codex) (OpenAI's terminal coding agent). You give it a goal; it scaffolds
a local task queue, then keeps running Codex — one task at a time — until your tests
pass or the loop hits a real blocker.

**Typical use:** you have a coding task too big for a single prompt. You want Codex
to keep working on it while you do something else, and stop only when it is actually done.

**Not a good fit for:** quick one-off edits, questions, or tasks with no clear pass/fail test.
For those, just use Codex directly.

## How It Works (in brief)

1. **One-time setup:** trust your project directory and the worktree parent in `~/.codex/config.toml` (details in [Prerequisites](#prerequisites)).
2. `codex-loop init --prompt "..."` — turns your goal into local files: a spec, a plan,
   numbered task documents, and a config (`codex-loop.yaml`).
3. Commit those files so Codex can see them: `git add -A && git commit -m "add codex-loop files"`
4. `codex-loop run` — works through each task in order, running Codex and your
   verification commands after every iteration. Stops when everything passes, or
   when it is genuinely stuck.
5. `git merge codex-loop/<branch>` — merge the changes into your main branch when the loop completes.
   (`codex-loop run` prints the exact command when it finishes. Your working directory is unchanged until you do this.)
6. `codex-loop cleanup --apply` — remove the worktree and old log artifacts after merging. (Does not delete your code or git history.)

At any time: `codex-loop status --summary` shows what is happening, and `codex-loop events --limit 10` shows the iteration timeline.

All state lives on disk in your project directory, so runs are resumable and inspectable.

**Your existing code is safe:** Codex works in an isolated Git branch (`codex-loop/...`), not
directly on your main branch. Nothing changes in your working directory until you explicitly
run `git merge`. If you don't like the result, just don't merge — your original code is untouched.

```
$ codex-loop run
Codex working in: /path/to/.codex-loop-worktrees/my-project/codex-loop-001-add-validation-20250610/ (isolated Git branch — your project files are unchanged until you merge)
[iteration 1/30] task: 001-add-validation  (0/2 done, running Codex...) [10:15:02]
  (waiting for Codex — this can take up to 30 minutes per iteration; run 'codex-loop events --limit 10' in another terminal to watch)
  -> status=continue verification=FAIL files_changed=3
     verification error (last 300 chars):
     FAILED tests/test_forms.py::test_email_validation - AssertionError: expected ValidationError
[iteration 2/30] task: 001-add-validation  (0/2 done, running Codex...) [10:31:18]
  (waiting for Codex — this can take up to 30 minutes per iteration; run 'codex-loop events --limit 10' in another terminal to watch)
  -> status=complete verification=pass files_changed=2
[iteration 3/30] task: 002-write-tests  (1/2 done, running Codex...) [10:47:55]
  (waiting for Codex — this can take up to 30 minutes per iteration; run 'codex-loop events --limit 10' in another terminal to watch)
  -> status=complete verification=pass files_changed=4
All tasks done and verification passed.
completed
Changes are on branch: codex-loop/my-project-a1b2c3
(Your working directory is unchanged until you merge.)

Run these commands from your project directory:

  # 1. Review the changes (optional)
  git diff --stat main..codex-loop/my-project-a1b2c3

  # 2. Merge into your main branch
  git checkout main
  git merge codex-loop/my-project-a1b2c3

  # 3. Clean up worktree and old artifacts
  codex-loop cleanup --apply
```

**Ready to start?** → [Prerequisites](#prerequisites) → [Install](#install) → [Quick Start](#quick-start).

**Want to try a complete worked example first?** → [examples/simple-local-project](examples/simple-local-project/README.md) — a self-contained todo CLI project you can run without touching your own code.

**Time to first run:** ~5 minutes if you already have Python 3.11+, Node.js, Codex CLI, and an OpenAI API key. Allow 20–30 minutes if you need to install any of those first (see [Prerequisites](#prerequisites)). Each Codex iteration takes 5–30 minutes; a small task (2–3 iterations) typically completes in under an hour.

## Prerequisites

**Platform:** macOS and Linux. Windows is not supported (requires Git worktrees and Unix process management). The `service` subcommand is macOS-only (launchd); all other commands work on Linux too. Windows users can run `codex-loop` inside [WSL 2](https://learn.microsoft.com/en-us/windows/wsl/install) (Windows Subsystem for Linux).

**Quick check** — run these to confirm you're ready:

```bash
python3 --version    # need 3.11 or newer
codex --version      # need Codex CLI installed
echo $OPENAI_API_KEY # need a non-empty API key
```

If any of those fail, see the details below. Otherwise skip straight to [Install](#install).
(The Git requirement is checked when you run `codex-loop run` — it will tell you if anything is missing.)

Before installing `codex-loop`, make sure you have:

1. **Python 3.11+** — check with `python3 --version`
   If you have an older version, upgrade via [python.org](https://www.python.org/downloads/) or Homebrew: `brew install python@3.11`
2. **[Codex CLI](https://github.com/openai/codex)** installed and working — install via npm or Homebrew:
   ```bash
   npm install -g @openai/codex   # requires Node.js 16+; if npm is not found: brew install node
   # or
   brew install --cask codex
   ```
   Verify: `codex --version`
3. **OpenAI API key** — get one at [platform.openai.com/api-keys](https://platform.openai.com/api-keys), then set it in your shell:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```
   To make it permanent, add that line to your `~/.zshrc` or `~/.bashrc`.
   **Cost:** each iteration calls Codex with a large prompt and expects a structured response. A typical small task (3–10 iterations) costs roughly $0.10–$1.00 depending on the model and codebase size. Set a spending limit on your OpenAI account before running long unattended loops.
   **Model access:** `codex-loop` defaults to `gpt-5.4`. If your API key does not have access to that model, pass `--model` to `init` — it is automatically written into `codex-loop.yaml`:
   ```bash
   codex-loop init --prompt "..." --model o3
   ```
   Common alternatives: `o3`, `o4-mini`.
4. **A local Git repository with at least one commit** — if starting fresh: `git init && git add -A && git commit -m 'init'`
   (After running `codex-loop init`, the `.codex-loop/` directory is automatically added to `.gitignore` — do not commit it.)
5. **Project directory trusted by Codex** — `codex exec` refuses to run in untrusted directories.
   You need to trust **two** paths:
   - Your project directory (needed for `codex-loop init`)
   - The worktree parent `../.codex-loop-worktrees/` (needed for `codex-loop run`, which runs Codex
     inside an isolated Git worktree next to your project)

   Easiest setup — run this **inside your project directory** to append the correct entries automatically:
   ```bash
   mkdir -p ~/.codex && printf '\n[projects."%s"]\ntrust_level = "trusted"\n\n[projects."%s/.codex-loop-worktrees"]\ntrust_level = "trusted"\n' "$(pwd)" "$(dirname $(pwd))" | tee -a ~/.codex/config.toml
   ```
   This appends (never overwrites) to the file. Verify both entries were added: `cat ~/.codex/config.toml`
   The result should look like:
   ```toml
   [projects."/Users/alice/code/my-app"]
   trust_level = "trusted"

   [projects."/Users/alice/code/.codex-loop-worktrees"]
   trust_level = "trusted"
   ```

## Install

> **Platform note:** macOS and Linux only. Windows is not supported.

`codex-loop` has no third-party Python dependencies — just Python 3.11+ and the tools you already have.

> **Note on the repo name:** the repository is called `codex-loop-skill` (it also ships a Codex skill), but the installed CLI command is `codex-loop`. After installing, use `codex-loop` — not `codex-loop-skill`.

> **Where to clone:** run these commands from your **home directory** (or any permanent location — NOT inside your project). The `codex-loop-skill` directory must stay in place after installing.

```bash
cd ~   # or wherever you keep tools — NOT inside your project directory
git clone https://github.com/ly87ing/codex-loop-skill.git
cd codex-loop-skill
python3 -m pip install -e .
cd ..   # go back — next, cd into YOUR project directory (not this one)
```

> **Note:** `-e` (editable install) means the `codex-loop-skill` directory must stay where it is — do not move or delete it after installing.

> **If you get "externally managed environment" error** (common on macOS with Homebrew Python):
> use `pipx` instead (see Tip below), or add `--break-system-packages` to the pip command:
> ```bash
> python3 -m pip install -e . --break-system-packages
> ```

> **Tip:** if you use virtual environments and want `codex-loop` available everywhere without activating one,
> install with `pipx` instead (run this from the **parent** of `codex-loop-skill`, i.e. after `cd ..`):
> ```bash
> pipx install -e ./codex-loop-skill
> pipx ensurepath   # adds pipx bin dir to PATH; then open a new terminal
> ```
> (Avoids the `command not found` issue without touching your system Python.)
> **Note:** the `-e` flag applies here too — the `codex-loop-skill` directory must stay in place after installing.

Verify it worked:

```bash
codex-loop --help
# If you get 'command not found', see Troubleshooting below.
```

Now go to **your own project directory** (not `codex-loop-skill`) to use it:

```bash
cd /path/to/your-project   # your existing project, or create one: mkdir my-project && cd my-project
```

To upgrade later:

```bash
cd codex-loop-skill   # go into the cloned repo directory
git pull              # fetch the latest changes
# No reinstall needed — the -e install picks up changes automatically.
# (If codex-loop --help fails after pulling, re-run: python3 -m pip install -e .)
```

## Quick Start

The minimum path to get started. Run these inside **your own project directory** (not inside the `codex-loop-skill` repo you just cloned).

**Step 0 — One-time setup** (skip if already done):

1. Set your OpenAI API key (both `init` and `run` need it):
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```
   To make it permanent, add that line to your `~/.zshrc` or `~/.bashrc`.
2. Make sure your project is a Git repo with at least one commit:
   ```bash
   git init && git add -A && git commit -m "init"
   ```
3. Trust your project directory and the worktree parent in `~/.codex/config.toml`.
   Run these commands **inside your project directory** — they append the correct entries automatically:
   ```bash
   mkdir -p ~/.codex && printf '\n[projects."%s"]\ntrust_level = "trusted"\n\n[projects."%s/.codex-loop-worktrees"]\ntrust_level = "trusted"\n' "$(pwd)" "$(dirname $(pwd))" | tee -a ~/.codex/config.toml
   ```
   > **Why two entries?** Both `codex-loop init` and `codex-loop run` call `codex exec`, which refuses to run in untrusted directories.
   > The first entry trusts your project directory (needed for `init`). The second trusts the worktree parent (needed for `run`, which runs Codex in an isolated Git worktree next to your project).
   > Without both entries you will see "Not inside a trusted directory".

   Verify both entries were added: `cat ~/.codex/config.toml`

   > **Prefer editing manually?** Open `~/.codex/config.toml` in any text editor and *append* these lines
   > (replace the paths with your actual project directory — run `pwd` to find it):
   > ```toml
   > [projects."/Users/alice/code/my-app"]
   > trust_level = "trusted"
   >
   > [projects."/Users/alice/code/.codex-loop-worktrees"]
   > trust_level = "trusted"
   > ```
   > **Important:** if the file already exists, *append* these entries — do not delete anything already in the file.

**Steps 1–6 — Run the loop:**

```bash
# Move into your own project first
cd /path/to/your-project

# 1. Scaffold workflow files from your goal
#    A good prompt names the language/framework, what to build, and how to test it.
#    Examples:
#      "Add input validation to every form in this app (Python/Flask). Tests in pytest."
#      "Implement a REST API endpoint for user registration (Node/Express). Tests in jest."
#      "Refactor the database layer to use SQLAlchemy. Tests in pytest."
codex-loop init --prompt "Add input validation to every form in this app (Python/Flask). Tests in pytest."
# If you get a model access error, add: --model o3
#   codex-loop init --prompt "..." --model o3
# (--model is automatically written into codex-loop.yaml — no manual edit needed)
# (This calls Codex to generate your project files — usually takes 30–90 seconds.
#  The terminal is quiet while Codex works — that silence is normal, not a hang.)
# Success looks like:
#   Initialized codex-loop files in /your/project
#
#   Next steps:
#     1. Skim the generated files ...
#     2. Confirm verification.commands in codex-loop.yaml ...
#     3. Commit the generated files: git add -A && git commit -m 'add codex-loop files'
#     4. Run: codex-loop run
#   (plus trust config reminders for ~/.codex/config.toml)

# 2. Review generated files — especially the verification command
#    Open codex-loop.yaml in your editor and confirm verification.commands matches
#    how you actually run your tests (this is the most important field):
cat codex-loop.yaml
#    Example — if your project uses pytest:
#      "verification": { "commands": ["python -m pytest tests/ -q"] }
#    Tip: run that command manually now to confirm it works before starting the loop.
#    Note: codex-loop.yaml uses JSON syntax (not indented YAML) — that is normal.
#    Fields worth knowing: verification.commands (required), execution.max_iterations (iteration cap),
#    codex.model (Codex model). Everything else can be left at defaults.
#    Do NOT change execution.sandbox or execution.approval — required for unattended runs.
#    Also skim spec/, plan/, and tasks/ to make sure the goal was captured correctly.
#    If the output looks wrong, re-run with a better prompt:
#      codex-loop init --prompt "..." --force
#    WARNING: --force deletes all existing state and run history. Only use it before you run
#    'codex-loop run' for the first time, or when you intentionally want to start over.

# 3. Commit the generated files so Codex can see them in its isolated worktree
#    (codex-loop run creates a Git worktree from your latest commit — files not
#    committed yet are invisible to Codex)
#    If git commit fails with 'Author identity unknown', set your Git identity first:
#      git config --global user.email "you@example.com"
#      git config --global user.name "Your Name"
git add -A && git commit -m "add codex-loop files"

# 4. Confirm ~/.codex/config.toml has both trust entries
#    (codex-loop run runs Codex in a worktree next to your project — both paths must be trusted)
#    If you already did Step 0 above, both entries are already in place — just verify:
#      cat ~/.codex/config.toml
#    Otherwise, run this inside your project directory to append the correct entries:
mkdir -p ~/.codex && printf '\n[projects."%s"]\ntrust_level = "trusted"\n\n[projects."%s/.codex-loop-worktrees"]\ntrust_level = "trusted"\n' "$(pwd)" "$(dirname $(pwd))" | tee -a ~/.codex/config.toml
#    Then verify:
#      cat ~/.codex/config.toml

# 5. Run the loop — it will keep working until done or genuinely blocked
#    Note: Codex runs in an isolated Git worktree containing only committed files.
#    If your tests need untracked files (e.g. .env, node_modules), add a hook:
#      "hooks": { "pre_iteration": ["cp /path/to/.env $CODEX_LOOP_WORKING_DIR/"] }
#    See 'Known Limits' in this README for details.
#    Each iteration calls Codex and waits up to 30 minutes for a response.
#    A typical small task takes 3–10 iterations (15 minutes to a few hours).
#    Each iteration shows one progress line before Codex starts, then goes quiet
#    while Codex works (up to 30 min per iteration) — silence during that gap is normal.
#    A result line is printed after each iteration completes.
#    To see a human-readable timeline at any time, open another terminal and run:
#      codex-loop events --limit 10
#    (For raw Codex output: codex-loop logs tail --lines 50)
#    You can press Ctrl-C at any time to stop safely; the next run picks up where it left off.
#    If the loop stops with 'blocked', see 'If the loop blocks' section below for common causes and fixes.
codex-loop run
# You will see output like:
#   Codex working in: /path/to/.codex-loop-worktrees/my-project/codex-loop-.../ (isolated Git branch — your files unchanged until you merge)
#   [iteration 1/30] task: 001-foundation  (0/2 done, running Codex...) [14:23:01]
#     (waiting for Codex — this can take up to 30 minutes per iteration; run 'codex-loop events --limit 10' in another terminal to watch)
#     -> status=continue verification=FAIL files_changed=3
#        ("continue" = Codex is still working on it; "FAIL" = tests not passing yet — this is normal)
#        verification error (last 300 chars):
#        FAILED tests/test_todo.py::test_add - AssertionError: expected 1 item, got 0
#   [iteration 2/30] task: 001-foundation  (0/2 done, running Codex...) [14:31:45]
#     (waiting for Codex — this can take up to 30 minutes per iteration; run 'codex-loop events --limit 10' in another terminal to watch)
#     -> status=complete verification=FAIL files_changed=2
#        ("complete" = Codex thinks it's done, but tests still fail — loop keeps going automatically)
#   [iteration 3/30] task: 001-foundation  (0/2 done, running Codex...) [14:39:12]
#     (waiting for Codex — this can take up to 30 minutes per iteration; run 'codex-loop events --limit 10' in another terminal to watch)
#     -> status=complete verification=pass files_changed=3
#        ("complete" + "pass" = task verified done; loop moves to next task)
#   All tasks done and verification passed.
#   completed
#   Changes are on branch: codex-loop/my-project-abc123
#   (Your working directory is unchanged until you merge.)
#
#   Run these commands from your project directory:
#
#     # 1. Review the changes (optional)
#     git diff --stat main..codex-loop/my-project-abc123
#
#     # 2. Merge into your main branch
#     git checkout main
#     git merge codex-loop/my-project-abc123
#
#     # 3. Clean up worktree and old artifacts
#     codex-loop cleanup --apply

# Note: Codex writes all changes to an isolated Git branch, not your project directory.
#       You won't see any changed files locally until you merge in step 6.

# 6. Merge the changes
#    When the loop completes, it prints the exact commands to run. Copy and run them:
#      git checkout main   # or master, or your default branch
#      git merge codex-loop/<branch>   # use the branch name printed above
#    If you need to find the branch name later:
#      git branch | grep codex-loop
#    After merging, clean up old log/run artifacts (does NOT delete your code or git history):
codex-loop cleanup --apply

# 7. Check status at any time
codex-loop status --summary
# If something looks wrong: codex-loop doctor   (checks config, tasks, and state)
```

Example output (while running):

```
project: my-project
overall_status: running          # running | completed | blocked
iteration: 3
no_progress_iterations: 0        # iterations with no file changes (resets on progress)
tasks:
  [x] 001-create-schema  (done)
  [~] 002-add-api        (in_progress)
  [ ] 003-write-tests    (ready)
current_task: 002-add-api
runner_failures_total: 0         # total codex exec failures so far
verification_failures_total: 2   # total failed verification runs so far
worktree_branch: codex-loop/my-project-abc123
```

When the run finishes successfully (`overall_status: completed`), `codex-loop status --summary` also prints the merge commands:

```
project: my-project
overall_status: completed
...
worktree_branch: codex-loop/my-project-abc123

Next steps (all tasks done):
  # 1. Review the changes (optional)
  git diff --stat main..codex-loop/my-project-abc123

  # 2. Merge into your main branch
  git checkout main
  git merge codex-loop/my-project-abc123

  # 3. Clean up worktree and old artifacts
  codex-loop cleanup --apply
```

Task markers: `[x]` done, `[~]` in progress, `[!]` blocked, `[ ]` pending.
If `overall_status` is `blocked`, the loop stopped — run `codex-loop run --retry-blocked` to retry.

That is all you need for most tasks. The loop stops by itself when all tasks pass verification,
or when it hits a real blocker (no progress, too many failures).
If something goes wrong, see the [Troubleshooting](#troubleshooting) section below for common errors and fixes.

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
(Your working directory is unchanged until you merge.)

Run these commands from your project directory (/path/to/your-project):

  # 1. Review the changes (optional)
  git diff --stat main..codex-loop/my-project-abc123

  # 2. Merge into your main branch
  git checkout main
  git merge codex-loop/my-project-abc123

  # 3. Clean up worktree and old artifacts
  codex-loop cleanup --apply
```

The exact branch name is printed by the loop — copy it from your terminal output. Or inspect the changes first:

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
# The codex-loop/... Git branch is NOT deleted — to remove it too:
#   git branch -d codex-loop/<branch-name>
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

`--force` is required because `codex-loop.yaml` and the task files already exist. It will replace them with a fresh scaffold for the new goal. Your source code and git history are not affected — only the codex-loop workflow files (`codex-loop.yaml`, `spec/`, `plan/`, `tasks/`, `.codex-loop/`) are overwritten.

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
codex-loop doctor              # checks config, tasks, and state — prints specific hints
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

If retrying still blocks, common fixes:

- **`no_progress_limit`** (no file changes): the task description may be too vague or too large. Edit the task file in `tasks/` to be more specific or split it into smaller steps, **commit the change** (`git add -A && git commit -m 'refine task'`), then: `codex-loop run --retry-blocked`.
- **`runner_failure_circuit_breaker`** (Codex exec keeps failing): check your API key, network, and Codex version (`codex --version`). Update with `npm install -g @openai/codex`.
- **`verification_failure_circuit_breaker`** (tests always fail): the verification command may be wrong — check `verification.commands` in `codex-loop.yaml`. Run it manually to confirm it works. See `codex-loop events --limit 20` for the test output.
- **Increase the iteration budget**: edit `execution.max_iterations` in `codex-loop.yaml` (default: 30) if the task is large or the tests are flaky. A rule of thumb: allow roughly 5–10 iterations per task file.

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

# Codex runs in an isolated Git worktree — managed automatically, no need to navigate there
```

## Task File Format

Each file in `tasks/` is a Markdown document. The filename determines execution order (`001-`, `002-`, ...). The content is passed directly to Codex as the task description.

To declare that a task depends on another:

```markdown
<!-- depends_on: 001-foundation -->
```

The loop skips a task until all its dependencies are `done`. `codex-loop init` generates these automatically from your prompt.

You can edit task files freely before or between runs to tighten the description, split a task, or remove tasks you don't need. After editing:

1. Commit the changes: `git add tasks/ && git commit -m 'update task'`
   (Codex runs in an isolated Git worktree built from your latest commit — uncommitted edits are invisible to it.)
2. Run `codex-loop doctor --repair` to sync the state file.
3. Then `codex-loop run --retry-blocked` to resume.

**What makes a good task description?** The content is passed verbatim to Codex, so the more specific it is, the better the result:

```markdown
# Too vague (Codex may not know where to start)
Add validation to the app.

# Good (names the files, the rules, and the test to pass)
Add input validation to the registration form in `src/routes/auth.py`:
- email must match RFC 5322 format
- password must be at least 8 characters
Raise `ValueError` with a descriptive message on invalid input.
Tests in `tests/test_auth.py` must pass with `python -m pytest tests/test_auth.py -q`.
```

If `codex-loop init` generates tasks that are too vague, edit them before running, or re-run `init` with a more specific prompt.

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
- Too many consecutive `codex exec` failures (configurable limit — stops the loop from spinning on a broken setup)
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

**Something not working? Start here:**

```bash
codex-loop doctor        # checks config, task files, and state — prints specific hints
codex-loop status --summary  # shows current task, last blocker, iteration count
codex-loop events --limit 10 # shows what happened in recent iterations
```

Then look up your specific error below.

### `codex-loop: command not found`

The `codex-loop` command is installed by pip into a user scripts directory that may not be on your PATH.

Fix with pipx (recommended — run from the **parent** directory of `codex-loop-skill`):

```bash
pipx install -e ./codex-loop-skill
pipx ensurepath   # adds pipx bin dir to PATH if not already there
# Then open a new terminal window (or run: source ~/.zshrc)
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

### "error: externally-managed-environment" during install

On macOS with Homebrew Python (or some Linux distros), pip refuses to install globally.
The recommended fix is `pipx` (run from the **parent** directory of `codex-loop-skill`):

```bash
pipx install -e ./codex-loop-skill
pipx ensurepath
# Then open a new terminal
```

Or override the restriction (fine for a personal tool install):

```bash
python3 -m pip install -e . --break-system-packages
```

### "Codex could not authenticate" / API key error

Both `codex-loop init` and `codex-loop run` call `codex exec`, which exits immediately if
`OPENAI_API_KEY` is not set or is invalid. Get a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys).

```bash
export OPENAI_API_KEY="sk-..."
```

To make it permanent, add that line to your `~/.zshrc` or `~/.bashrc`.

### "Model not found" / model access error

`codex-loop` defaults to `gpt-5.4`, which requires special API access. If you see an error like
`model not found`, `invalid model`, or `you do not have access to this model`, use a different model:

```bash
# Re-run init with a supported model (--model is written into codex-loop.yaml automatically)
codex-loop init --prompt "..." --model o3
# or
codex-loop init --prompt "..." --model o4-mini
```

If you already ran `init` and just need to change the model, edit `codex-loop.yaml` directly:
```json
"codex": { "model": "o3" }
```
Then verify the file is valid JSON: `python3 -m json.tool codex-loop.yaml`

### "Not inside a trusted directory"

Both `codex-loop init` and `codex-loop run` call `codex exec`, which refuses to run in
directories that Codex has not explicitly trusted.

**Important:** `codex-loop run` runs Codex inside an isolated Git worktree at a path like
`../.codex-loop-worktrees/<project>/<branch>/` — a different directory from your project.
Trusting only your project directory is not enough; you need to trust the worktree parent too.

The error message will print the exact path that needs to be trusted.
For `codex-loop init` failures, the missing path is your project directory.
For `codex-loop run` failures, it is usually the worktree parent.
The quickest fix — run this **inside your project directory** to append the correct entries directly:

```bash
mkdir -p ~/.codex && printf '\n[projects."%s"]\ntrust_level = "trusted"\n\n[projects."%s/.codex-loop-worktrees"]\ntrust_level = "trusted"\n' "$(pwd)" "$(dirname $(pwd))" | tee -a ~/.codex/config.toml
```

This appends (never overwrites) to the file. Verify both entries are present:
```bash
cat ~/.codex/config.toml
```

Alternatively, run `codex` once interactively inside each directory to trigger the interactive
trust prompt (but you would need to do that after the worktree is created, so the `config.toml`
approach above is easier).

### "not inside a Git repository"

`codex-loop run` requires a Git repository with at least one commit.
If you see this error, initialize the repository first:

```bash
git init
git add -A
git commit -m "init"
```
(`.codex-loop/` is automatically added to `.gitignore` by `codex-loop init`, so `git add -A` is safe.)

### "Another codex-loop run is already active"

This means a previous run left a lock file behind (usually because it was force-killed or crashed).
The error message prints the exact `kill` and `rm` commands to unblock:

```bash
# If the listed PID is no longer running, delete the lock file directly:
rm .codex-loop/run.lock

# Then re-run:
codex-loop run
```

If the PID is still alive (a run genuinely in progress), wait for it to finish or stop it first:

```bash
kill <pid>   # use the PID shown in the error message
```

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
| `no_progress_limit` | Codex made no file changes for 5 consecutive iterations (default) | Review the task description; make it more specific, then `git add -A && git commit -m 'refine task'` and `codex-loop run --retry-blocked` |
| `runner_failure_circuit_breaker` | `codex exec` failed repeatedly | Check your API key and network; run `codex` manually to verify |
| `verification_failure_circuit_breaker` | Tests kept failing | Look at `codex-loop events --limit 20` for the error output |
| `task_failure_circuit_breaker` | One task failed too many times; loop continues with next task | Check `codex-loop status --summary` to see which task was skipped |
| `max_iterations` | Hit the iteration cap | Increase `max_iterations` in `codex-loop.yaml` or break the task into smaller pieces |
| `agent_blocked` | Codex reported it is stuck and cannot continue | Edit the relevant task file to give more context, `git add -A && git commit -m 'refine task'`, then `codex-loop run --retry-blocked` |
| `no_selectable_task` | All remaining tasks are waiting on dependencies that are not done | Check `codex-loop status --summary`; a dependency task may be blocked and need `--retry-blocked` |

After fixing the root cause:

```bash
codex-loop run --retry-blocked
```

### Verification keeps failing

The loop injects the last failed verification output into the next prompt automatically.
If it keeps failing, the test command itself may be wrong.

Note: verification commands run inside the **worktree** (the isolated Git branch), not your project directory.
To reproduce what the loop sees, run from the worktree path printed by `codex-loop run`:

```bash
# Find the worktree path
codex-loop status --summary   # shows worktree_branch
git worktree list              # shows all worktree paths

# Run your verification command from the worktree directory
cd /path/to/.codex-loop-worktrees/my-project/codex-loop-...
python -m pytest tests/ -q
```

Or run it from your project directory to check the command syntax is correct (results may differ if files are not yet committed):

```bash
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

After editing, verify the file is valid JSON (`python3 -m json.tool codex-loop.yaml`), then: `codex-loop run --retry-blocked`.

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
python3 -m json.tool codex-loop.yaml
```

The error message will show the line number. Common mistakes: trailing commas, missing quotes around keys, single quotes instead of double quotes, comments (JSON does not support `//` or `#` comments). If the file is beyond repair, re-generate it with:

```bash
codex-loop init --prompt "your goal" --force
```

### How do I see what Codex is actually doing?

While the loop runs, Codex output is captured internally (not shown live) so the supervisor can parse the JSON result.

For a human-readable summary of what happened in recent iterations (recommended):

```bash
codex-loop events --limit 10
```

Example output:
```
2025-06-10T14:23:01+00:00 iteration:continue task=001-foundation iteration 1: wrote Storage class skeleton
2025-06-10T14:39:45+00:00 iteration:continue task=001-foundation iteration 2: added argparse subcommands, tests still failing
2025-06-10T14:55:03+00:00 iteration:complete task=001-foundation iteration 3: all tests passing
2025-06-10T15:10:22+00:00 iteration:complete task=002-core-commands iteration 4: implemented add/list/done/delete
```

To see the raw Codex output (one JSON object per line — useful for debugging):

```bash
codex-loop logs tail --lines 50
```

### I edited task files or `codex-loop.yaml` manually

After editing, commit the changes so Codex can see them (it runs in an isolated Git worktree built from your latest commit — uncommitted edits are invisible to it):

```bash
git add -A && git commit -m 'update task'
codex-loop doctor --repair
codex-loop run --retry-blocked
```

### `git merge` reports conflicts

If Codex edited files that you also modified since the run started, Git may report merge conflicts.
Resolve them as you normally would:

```bash
# After git merge codex-loop/<branch> reports conflicts:
git status                  # see which files have conflicts
# Edit the conflicting files to resolve the <<< === >>> markers
git add <resolved-files>
git commit                  # complete the merge
```

Alternatively, inspect the changes first and decide what to keep:

```bash
git diff main..codex-loop/<branch>   # see exactly what Codex changed
```

If the conflicts are too complex and you want to start fresh, discard the merge and the branch:

```bash
git merge --abort            # cancel the in-progress merge
codex-loop cleanup --apply   # remove worktrees and old artifacts
```

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
  Common cases: `.env` files (copy them in), `node_modules/` (run `npm install` rather than copying — it's faster), Python virtualenvs (run `pip install -e .` or `pip install -r requirements.txt` in the worktree). The worktree path is also available as `$CODEX_LOOP_WORKING_DIR` in hooks. Alternatively, use the full interpreter path in `verification.commands` (e.g. `".venv/bin/python -m pytest tests/ -q"`) — see [Verification keeps failing](#verification-keeps-failing).
- Each iteration waits up to **30 minutes** for Codex to respond (`iteration_timeout_seconds: 1800` in `codex-loop.yaml`). A progress line is printed when each iteration starts; the terminal then goes quiet while Codex works — that silence is normal. A result line is printed when the iteration completes. Run `codex-loop events --limit 10` to see a summary of recent iterations, or reduce `iteration_timeout_seconds` in `codex-loop.yaml` if you need a shorter timeout.
- `codex-loop.yaml` uses JSON syntax (curly braces and quoted keys), not indented YAML. This is intentional — it avoids a PyYAML dependency. Edit it with any text editor; just keep the JSON structure intact. If you break it accidentally, check with: `python3 -m json.tool codex-loop.yaml`
- Codex CLI approval behavior can vary by CLI version. This project passes `approval_policy="never"` to `codex exec`, but some Codex releases have edge cases where Codex still pauses for interactive input. If an iteration hangs for more than 30 minutes (the default `iteration_timeout_seconds`), it will time out and be counted as a runner failure. If you see repeated runner failures with no clear error, update Codex CLI: `npm install -g @openai/codex` (or `brew upgrade --cask codex`).
- Some Codex resume failures are only detectable from CLI error text, so session fallback is heuristic rather than protocol-level.
- Task execution is sequential in the first version. There is no parallel task scheduler yet.

## Skill

This repository also ships a Codex skill at `skills/codex-loop/SKILL.md`. The skill teaches Codex when and how to use `codex-loop` — so instead of running CLI commands yourself, you can just describe your goal to Codex and it will call `codex-loop init`, review the output, and start the loop for you.

To use it, run these commands from the directory where you cloned `codex-loop-skill`:

```bash
mkdir -p ~/.codex/skills
ln -s "$(pwd)/skills/codex-loop" ~/.codex/skills/codex-loop
```

(Run `pwd` first if you're unsure of the path — the symlink must point to the actual location on disk.)

(This creates a symlink so Codex always uses the latest version when you `git pull`.)

Codex will pick it up automatically on the next run.

To verify it was installed:

```bash
ls ~/.codex/skills/codex-loop
# Should show: SKILL.md  references/
```

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
