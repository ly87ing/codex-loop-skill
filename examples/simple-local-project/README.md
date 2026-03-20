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
cd my-todo-project

# 3. Trust the directory in Codex (run once interactively, then Ctrl-C)
codex

# 4. Run the loop
codex-loop run

# 5. Watch progress
codex-loop status --summary
```

The loop will implement `todo.py` and `tests/test_todo.py` across two tasks,
then stop automatically when `python -m pytest tests/ -q` passes.

## What a blocked run looks like

If the loop stops before completing:

```bash
codex-loop status --summary   # see which task is blocked and why
codex-loop events --limit 20  # see the full event timeline

# Retry with continuous mode
codex-loop run --continuous --retry-blocked --cycle-sleep-seconds 60
```
