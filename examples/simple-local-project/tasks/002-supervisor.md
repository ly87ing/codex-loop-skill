# Core Commands

<!-- depends_on: 001-foundation -->

Implement all four subcommands in `todo.py`:

- `add <title>`: load existing tasks, append a new `Task` with auto-incremented ID, save, print the new ID
- `list`: load and print every task as `[id] [status] title` (one per line)
- `done <id>`: find the task with matching ID, set `status = "done"`, save; print an error if ID not found
- `delete <id>`: remove the task with matching ID, save; print an error if ID not found

Then create `tests/test_todo.py` with `pytest` tests using `tmp_path` to isolate storage.
Cover: add a task, list tasks, mark done, delete, and done/delete with a missing ID.

Verification: `python -m pytest tests/ -q` must pass with no failures or errors.
