# Foundation

Create `todo.py` with a `Storage` class that reads and writes `todos.json`,
a `Task` dataclass with `id` (int), `title` (str), and `status` (str, default `"pending"`) fields,
and an `argparse`-based CLI skeleton with four subcommands registered but not yet implemented:
`add`, `list`, `done`, `delete`.

The file must be importable without side effects (guard the `main()` call under `if __name__ == "__main__"`).
