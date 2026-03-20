from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


TASK_PATTERN = re.compile(r"^\d{3}-.+\.md$")
# Matches: <!-- depends_on: 001-foo, 002-bar -->
_DEPENDS_ON_COMMENT = re.compile(
    r"<!--\s*depends_on\s*:\s*(.*?)\s*-->",
    re.IGNORECASE | re.DOTALL,
)
# Matches YAML frontmatter depends_on line: depends_on: 001-foo, 002-bar
_DEPENDS_ON_YAML = re.compile(
    r"^depends_on\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(slots=True)
class Task:
    task_id: str
    path: Path
    title: str
    body: str
    depends_on: list[str] = field(default_factory=list)


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
            depends_on = self._extract_depends_on(body)
            tasks.append(
                Task(task_id=path.stem, path=path, title=title, body=body, depends_on=depends_on)
            )
        return tasks

    @staticmethod
    def _extract_title(path: Path, body: str) -> str:
        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return path.stem

    @staticmethod
    def _extract_depends_on(body: str) -> list[str]:
        """Parse depends_on from an HTML comment or YAML frontmatter.

        Supported formats in task markdown:
          <!-- depends_on: 001-foundation, 002-setup -->
          depends_on: 001-foundation, 002-setup   (in YAML frontmatter block)
        """
        # Try HTML comment first (works anywhere in the file)
        match = _DEPENDS_ON_COMMENT.search(body)
        if match:
            return _parse_dep_list(match.group(1))
        # Try YAML frontmatter (between leading --- markers)
        if body.startswith("---"):
            end = body.find("\n---", 3)
            if end != -1:
                frontmatter = body[3:end]
                match = _DEPENDS_ON_YAML.search(frontmatter)
                if match:
                    return _parse_dep_list(match.group(1))
        return []


def _parse_dep_list(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]
