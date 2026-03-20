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
| `tasks/002-supervisor.md` | Second task: implement all commands + write tests |

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
git add .
git commit -m "init"

# 3. Trust the directory in Codex (run once interactively, then Ctrl-C)
codex

# 4. Run the loop
codex-loop run
# When it finishes you will see something like:
#   completed
#   Changes are on branch: codex-loop/my-todo-project-abc123
#   To merge: git merge codex-loop/my-todo-project-abc123

# 5. Merge the changes
#    When the run completes it prints the exact command, e.g.:
#      To merge: git merge codex-loop/my-todo-project-abc123
#    Copy and run that printed command — do not guess the branch name.
#    If you need to find it later:
git branch | grep codex-loop
#    or: codex-loop status --summary  (shows worktree_branch)

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

## What a blocked run looks like

If the loop stops before completing, the reason is printed directly in the terminal:

```
blocked
Blocked: [no_progress_limit] No file changes detected for 4 consecutive iterations.
Run 'codex-loop status --summary' for full details.
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
