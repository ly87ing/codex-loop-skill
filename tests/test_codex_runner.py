from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_loop.codex_runner import CodexRunner
from codex_loop.task_graph import Task


class CodexRunnerTests(unittest.TestCase):
    def test_builds_exec_command_for_first_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = CodexRunner(root)

            command = runner.build_run_command(
                task=Task(
                    task_id="001-foundation",
                    path=root / "tasks" / "001-foundation.md",
                    title="Foundation",
                    body="# Foundation\n",
                ),
                prompt="Do the work",
                schema_path=root / ".codex-loop" / "agent_result.schema.json",
                output_path=root / ".codex-loop" / "runs" / "last.json",
                session_id=None,
                model="gpt-5.4",
            )

            self.assertEqual(command[:2], ["codex", "exec"])
            self.assertIn("--json", command)
            self.assertIn("--output-schema", command)
            self.assertIn("--output-last-message", command)

    def test_builds_resume_command_for_follow_up_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = CodexRunner(root)

            command = runner.build_run_command(
                task=Task(
                    task_id="001-foundation",
                    path=root / "tasks" / "001-foundation.md",
                    title="Foundation",
                    body="# Foundation\n",
                ),
                prompt="Continue the work",
                schema_path=root / ".codex-loop" / "agent_result.schema.json",
                output_path=root / ".codex-loop" / "runs" / "last.json",
                session_id="session-123",
                model="gpt-5.4",
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("session-123", command)


if __name__ == "__main__":
    unittest.main()

