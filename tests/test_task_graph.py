from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_loop.task_graph import TaskGraph


class TaskGraphTests(unittest.TestCase):
    def test_discovers_markdown_tasks_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir)
            (tasks_dir / "002-build-loop.md").write_text("# Build Loop\n\nImplement it.\n")
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nStart here.\n")

            tasks = TaskGraph(tasks_dir).discover()

            self.assertEqual([task.task_id for task in tasks], ["001-foundation", "002-build-loop"])
            self.assertEqual(tasks[0].title, "Foundation")
            self.assertEqual(tasks[1].title, "Build Loop")


    def test_depends_on_parsed_from_html_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir)
            (tasks_dir / "001-foundation.md").write_text(
                "# Foundation\n\n<!-- depends_on: 002-setup, 003-build -->\n"
            )

            tasks = TaskGraph(tasks_dir).discover()

            self.assertEqual(tasks[0].depends_on, ["002-setup", "003-build"])

    def test_depends_on_parsed_from_yaml_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir)
            (tasks_dir / "001-foundation.md").write_text(
                "---\ndepends_on: 002-setup\ntitle: Foundation\n---\n# Foundation\n"
            )

            tasks = TaskGraph(tasks_dir).discover()

            self.assertEqual(tasks[0].depends_on, ["002-setup"])

    def test_depends_on_comment_does_not_include_closing_marker(self) -> None:
        """Regression: --> from comment close must not appear in parsed deps."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir)
            (tasks_dir / "001-foundation.md").write_text(
                "# Foundation\n\n<!-- depends_on: 002-setup, 003-build -->\n"
            )

            tasks = TaskGraph(tasks_dir).discover()

            self.assertEqual(tasks[0].depends_on, ["002-setup", "003-build"])

    def test_depends_on_empty_when_not_specified(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")

            tasks = TaskGraph(tasks_dir).discover()

            self.assertEqual(tasks[0].depends_on, [])


if __name__ == "__main__":
    unittest.main()

