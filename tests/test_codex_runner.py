from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_loop.codex_runner import CodexRunner
from codex_loop.config import CodexLoopConfig
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
                sandbox="workspace-write",
                approval="never",
            )

            self.assertEqual(command[:2], ["codex", "exec"])
            self.assertIn("--json", command)
            self.assertIn("--output-schema", command)
            self.assertIn("--output-last-message", command)
            self.assertIn('approval_policy="never"', command)
            self.assertIn('sandbox_mode="workspace-write"', command)

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
                sandbox="read-only",
                approval="on-request",
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("session-123", command)
            self.assertIn('approval_policy="on-request"', command)
            self.assertIn('sandbox_mode="read-only"', command)

    def test_falls_back_to_fresh_exec_when_resume_session_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = CodexRunner(root)
            task = Task(
                task_id="001-foundation",
                path=root / "tasks" / "001-foundation.md",
                title="Foundation",
                body="# Foundation\n",
            )
            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "execution": {
                        "resume_fallback_to_fresh": True,
                        "iteration_timeout_seconds": 30,
                    },
                    "verification": {"commands": ["python -m unittest"]},
                },
                root,
            )
            schema_path = root / ".codex-loop" / "agent_result.schema.json"
            schema_path.parent.mkdir(parents=True, exist_ok=True)
            schema_path.write_text("{}", encoding="utf-8")

            calls: list[list[str]] = []
            output_path = root / ".codex-loop" / "runs" / "001-foundation-last.json"

            def invoke_side_effect(
                command: list[str],
                prompt: str,
                cwd: Path,
                *,
                timeout_seconds: int,
            ) -> str:
                del timeout_seconds
                del prompt, cwd
                calls.append(command)
                if command[:3] == ["codex", "exec", "resume"]:
                    raise RuntimeError("Codex command failed.\nSTDERR:\nSession not found")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    """
                    {
                      "status": "continue",
                      "summary": "Retried without resume.",
                      "task_id": "001-foundation",
                      "files_changed": ["src/app.py"],
                      "verification_expected": ["python -m unittest"],
                      "needs_resume": true,
                      "blockers": [],
                      "next_action": "Continue."
                    }
                    """.strip(),
                    encoding="utf-8",
                )
                return '{"session_id":"fresh-session"}\n'

            with patch.object(CodexRunner, "_invoke", side_effect=invoke_side_effect):
                result = runner.run_task(
                    config=config,
                    task=task,
                    state={"history": []},
                    working_directory=root,
                    resume_session="expired-session",
                )

            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][:3], ["codex", "exec", "resume"])
            self.assertEqual(calls[1][:2], ["codex", "exec"])
            self.assertNotEqual(calls[1][:3], ["codex", "exec", "resume"])
            self.assertTrue(result["resume_fallback_used"])
            self.assertEqual(result["resume_failure_reason"], "Session not found")


if __name__ == "__main__":
    unittest.main()
