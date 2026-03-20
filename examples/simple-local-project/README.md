# Example: Todo CLI

This directory is a complete example of what `codex-loop init` generates for a real project goal.
It shows a beginner-friendly task: build a command-line todo list tool in Python.

## What this example contains

| File/Dir | What it is |
|---|---|
| `codex-loop.yaml` | Project config — goal, model, verification command, circuit breakers |
| `spec/001-project-spec.md` | What the project does and when it is "done" |
| `plan/001-implementation-plan.md` | Step-by-step breakdown of the work |
| `tasks/001-foundation.md` | First task: scaffold the CLI skeleton |
| `tasks/002-core-commands.md` | Second task: implement all commands + write tests |

## How to run this example

> Make sure you have completed the [Prerequisites](../../README.md#prerequisites) first.

```bash
# 1. Install codex-loop (skip if already installed)
git clone https://github.com/ly87ing/codex-loop-skill.git
python3 -m pip install -e codex-loop-skill/

# 2. Copy this example into a fresh Git repository
git init my-todo-project
cp -r codex-loop-skill/examples/simple-local-project/* my-todo-project/
cd my-todo-project          # <-- must be inside the project from here on
git add -A
git commit -m "init"
```

**Step 3 — Trust the directories in Codex (REQUIRED before step 4)**

`codex-loop run` runs Codex inside an isolated Git worktree next to your project.
You must trust **two** paths in `~/.codex/config.toml`.
Open (or create) the file in any text editor and add:

```bash
mkdir -p ~/.codex   # create the directory if it doesn't exist yet
# then open ~/.codex/config.toml in your editor and add:
```

```toml
[projects."/Users/alice/code/my-todo-project"]
trust_level = "trusted"

[projects."/Users/alice/code/.codex-loop-worktrees"]
trust_level = "trusted"
```

Replace `/Users/alice/code` with the **parent directory** of `my-todo-project`.
Not sure of the path? Run `pwd` inside `my-todo-project` — that's the first path. The second is its parent with `/.codex-loop-worktrees` appended.
Skip either entry and `codex-loop run` will fail with "Not inside a trusted directory".

```bash
# Make sure OPENAI_API_KEY is set before running (both codex-loop init and run need it)
export OPENAI_API_KEY="sk-..."   # skip if already set

# 4. Run the loop
#    Each iteration prints a progress line, then goes quiet while Codex works
#    (up to 30 min per iteration) — silence during that gap is normal.
#    A result line is printed after each iteration completes.
#    To watch the timeline in another terminal: codex-loop events --limit 10
codex-loop run
# During the run you will see lines like:
#   [iteration 1/20] task: 001-foundation  (0/2 done, running Codex...) [14:23:01]
#     (waiting for Codex — this can take up to 30 minutes; run 'codex-loop events --limit 10' in another terminal to watch)
#     -> status=continue verification=FAIL files_changed=2
#        verification error (last 300 chars):
#        FAILED tests/test_todo.py::test_add - AssertionError: expected 1 item, got 0
#   [iteration 2/20] task: 001-foundation  (0/2 done, running Codex...) [14:39:45]
#     (waiting for Codex — this can take up to 30 minutes; run 'codex-loop events --limit 10' in another terminal to watch)
#     -> status=complete verification=pass files_changed=3
#   [iteration 3/20] task: 002-core-commands  (1/2 done, running Codex...) [14:55:12]
#     (waiting for Codex — this can take up to 30 minutes; run 'codex-loop events --limit 10' in another terminal to watch)
#     -> status=complete verification=pass files_changed=5
#   All tasks done and verification passed.
#   completed
#   Changes are on branch: codex-loop/my-todo-project-abc123
#   To inspect before merging:
#     git diff --stat main..codex-loop/my-todo-project-abc123
#   To merge:
#     git checkout main
#     git merge codex-loop/my-todo-project-abc123
#   After merging, clean up with: codex-loop cleanup --apply

# 5. Merge the changes
#    Copy the exact commands from step 4's output above — do NOT use the branch name here literally.
#    Example (replace the branch name with what was printed):
#      git checkout main
#      git merge codex-loop/my-todo-project-abc123
#    Then clean up old artifacts (does NOT delete your code or git history):
codex-loop cleanup --apply

# 6. Watch progress (or inspect after a blocked run)
codex-loop status --summary
```

The loop will implement `todo.py` and `tests/test_todo.py` across two tasks,
then stop automatically when `python -m pytest tests/ -q` passes.

## Key fields in codex-loop.yaml

Note: the file uses JSON syntax (curly braces, quoted keys) — that is intentional and normal.

Most fields can be left at their defaults. These are the ones worth knowing:

| Field | What it does | When to change it |
|---|---|---|
| `verification.commands` | Commands that must pass for the loop to declare success | **Always check this first** — make sure it matches how you run your tests |
| `codex.model` | The Codex model to use | Change if you want to use a different model |
| `execution.max_iterations` | Total iteration cap across all tasks | Increase for large tasks that need more attempts |
| `goal.done_when` | Human-readable completion criteria | Edit if the generated criteria don't match your real goal |

Everything else (`hooks`, `operator.cleanup`, `daemon`, etc.) can be ignored until you need it.

**Do not change** `execution.sandbox` or `execution.approval` — these are required for unattended runs. Changing them will cause `codex-loop run` to hang waiting for interactive input.

## What a blocked run looks like

If the loop stops before completing, the reason is printed directly in the terminal:

```
blocked
Blocked: [no_progress_limit] No file changes detected for 4 consecutive iterations.
Run 'codex-loop status --summary' for full details.
To retry: codex-loop run --retry-blocked
```

For more detail and to retry:

```bash
codex-loop status --summary   # see which task is blocked and why
codex-loop events --limit 20  # see the full event timeline

# Retry blocked tasks
codex-loop run --retry-blocked

# Or keep retrying automatically
codex-loop run --continuous --retry-blocked --cycle-sleep-seconds 60
```

Common causes and fixes:

| Blocker | What to do |
|---|---|
| `no_progress_limit` | The task description may be too vague. Edit the task file in `tasks/` to be more specific, then `codex-loop doctor --repair` before retrying. |
| `runner_failure_limit` | Check your API key and network. Run `codex --version` to confirm Codex is installed. Update with `npm install -g @openai/codex`. |
| `verification_failure_limit` | Check `verification.commands` in `codex-loop.yaml`. Run the command manually to see the real error. |
| `max_iterations` | Increase `execution.max_iterations` in `codex-loop.yaml` (default: 20 in this example). |

## Use this as a template for your own project

Once you've run this example, apply the same workflow to your real project:

```bash
# Go to your own project (must be a git repo with at least one commit)
cd /path/to/your-project

# Generate fresh spec, plan, and tasks for your goal
codex-loop init --prompt "Your goal here. Name the language, framework, and test tool."

# Check verification.commands in codex-loop.yaml, then run
codex-loop run
```

Tips for a good prompt:
- Name the language and framework: "Python/Flask", "Node/Express", "Go"
- Name the test tool: "tests in pytest", "tests in jest", "go test"
- Be specific: "add input validation to every form" not just "add validation"
