from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


TASK_PATTERN = re.compile(r"^\d{3}-.+\.md$")


@dataclass(slots=True)
class Task:
    task_id: str
    path: Path
    title: str
    body: str


class TaskGraph:
    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = tasks_dir

    def discover(self) -> list[Task]:
        if not self.tasks_dir.exists():
            return []
        files = sorted(
            [
                path
                for path in self.tasks_dir.iterdir()
                if path.is_file() and path.suffix == ".md" and TASK_PATTERN.match(path.name)
            ]
        )
        tasks: list[Task] = []
        for path in files:
            body = path.read_text(encoding="utf-8")
            title = self._extract_title(path, body)
            tasks.append(Task(task_id=path.stem, path=path, title=title, body=body))
        return tasks

    @staticmethod
    def _extract_title(path: Path, body: str) -> str:
        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return path.stem

