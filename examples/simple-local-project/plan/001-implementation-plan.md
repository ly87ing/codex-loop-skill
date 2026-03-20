# Implementation Plan: Todo CLI

## Step 1 — Foundation

Create `todo.py` with a `Storage` class that reads/writes `todos.json`.
Define a `Task` dataclass with `id`, `title`, `status` fields.
Wire up `argparse` with four subcommands: `add`, `list`, `done`, `delete`.

## Step 2 — Core Commands

Implement each subcommand:
- `add <title>`: append task, auto-increment ID, save, print new ID
- `list`: load and print all tasks (id, status, title)
- `done <id>`: find task by ID, set status to "done", save
- `delete <id>`: remove task by ID, save

## Step 3 — Tests and Verification

Create `tests/test_todo.py` using `pytest` and `tmp_path` fixture so tests
never touch the real `todos.json`. Cover add, list, done, delete, and the
edge case of marking a non-existent ID.

Verification command: `python -m pytest tests/ -q`
