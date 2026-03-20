# Project Spec: Todo CLI

## Goal

Build a command-line todo list tool in Python. Users can add tasks, list them, mark them done,
and delete them. All data is stored in a local JSON file.

## Done When

- `python todo.py add "Buy milk"` appends a task and prints its ID
- `python todo.py list` prints all tasks with status (pending / done)
- `python todo.py done <id>` marks a task complete
- `python todo.py delete <id>` removes a task
- `python -m pytest tests/ -q` passes with no failures
- The JSON storage file survives a process restart (data is not lost)

## Out of Scope

- No web UI, no database, no authentication
- No due dates or priorities in v1
