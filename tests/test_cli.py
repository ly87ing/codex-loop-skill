from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_loop.cli import main
from codex_loop.config import CodexLoopConfig
from codex_loop.init_flow import InitResult, TaskDraft
from codex_loop.state_store import StateStore


class CliTests(unittest.TestCase):
    def test_status_summary_prints_current_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "codex-loop.yaml").write_text(
                json.dumps(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                    }
                ),
                encoding="utf-8",
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["status", "--project-dir", str(root), "--summary"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("demo", stdout.getvalue())
            self.assertIn("001-foundation", stdout.getvalue())

    def test_logs_tail_prints_latest_log_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs_dir = root / ".codex-loop" / "logs"
            logs_dir.mkdir(parents=True)
            (logs_dir / "0001-first.jsonl").write_text("old\nline\n", encoding="utf-8")
            (logs_dir / "0002-second.jsonl").write_text(
                "one\ntwo\nthree\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    ["logs", "tail", "--project-dir", str(root), "--lines", "2"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(stdout.getvalue().strip().splitlines(), ["two", "three"])

    def test_events_command_prints_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["events", "--project-dir", str(root), "--limit", "10"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("runner_failure", stdout.getvalue())

    def test_events_command_can_emit_json_with_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.record_iteration(
                task_id="001-foundation",
                summary="Changed files",
                fingerprint="abc",
                files_changed=["src/a.py"],
                verification_passed=False,
                agent_status="continue",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "events",
                        "--project-dir",
                        str(root),
                        "--task-id",
                        "001-foundation",
                        "--event-type",
                        "iteration:continue",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["label"], "iteration:continue")

    def test_events_command_can_write_json_to_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.record_iteration(
                task_id="001-foundation",
                summary="Changed files",
                fingerprint="abc",
                files_changed=["src/a.py"],
                verification_passed=False,
                agent_status="continue",
            )
            output_path = root / "events.json"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "events",
                        "--project-dir",
                        str(root),
                        "--json",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn(str(output_path), stdout.getvalue())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["task_id"], "001-foundation")

    def test_cleanup_command_invokes_apply_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch("codex_loop.cli.run_cleanup") as cleanup_mock,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                cleanup_mock.return_value = type(
                    "CleanupReportStub",
                    (),
                    {
                        "dry_run": False,
                        "removed": [".codex-loop/logs/0001-old.txt"],
                        "kept": [".codex-loop/logs/0002-new.txt"],
                        "removed_worktrees": ["stale-worktree"],
                        "warnings": [],
                    },
                )()
                exit_code = main(
                    [
                        "cleanup",
                        "--project-dir",
                        str(root),
                        "--apply",
                        "--keep",
                        "1",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("removed: 1", stdout.getvalue())
            cleanup_mock.assert_called_once()

    def test_cleanup_command_passes_age_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch("codex_loop.cli.run_cleanup") as cleanup_mock,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                cleanup_mock.return_value = type(
                    "CleanupReportStub",
                    (),
                    {
                        "dry_run": True,
                        "removed": [],
                        "kept": [],
                        "removed_worktrees": [],
                        "warnings": [],
                    },
                )()
                exit_code = main(
                    [
                        "cleanup",
                        "--project-dir",
                        str(root),
                        "--keep",
                        "5",
                        "--older-than-days",
                        "14",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            cleanup_mock.assert_called_once_with(
                root.resolve(),
                apply=False,
                keep=5,
                older_than_days=14,
                remove_worktrees=True,
            )

    def test_cleanup_command_passes_directory_specific_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch("codex_loop.cli.run_cleanup") as cleanup_mock,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                cleanup_mock.return_value = type(
                    "CleanupReportStub",
                    (),
                    {
                        "dry_run": True,
                        "removed": [],
                        "kept": [],
                        "removed_worktrees": [],
                        "warnings": [],
                    },
                )()
                exit_code = main(
                    [
                        "cleanup",
                        "--project-dir",
                        str(root),
                        "--logs-keep",
                        "20",
                        "--prompts-older-than-days",
                        "30",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            cleanup_mock.assert_called_once_with(
                root.resolve(),
                apply=False,
                keep=10,
                older_than_days=None,
                remove_worktrees=True,
                directory_keep={"logs": 20},
                directory_older_than_days={"prompts": 30},
            )

    def test_init_fails_when_post_init_hook_policy_is_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stdout = io.StringIO()
            stderr = io.StringIO()
            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "verification": {"commands": ["python -m unittest"]},
                    "hooks": {
                        "post_init": ["echo fail"],
                        "failure_policy": "block",
                    },
                },
                root,
            )

            with (
                patch(
                    "codex_loop.cli.CodexRunner.initialize_from_prompt",
                    return_value=InitResult(
                        project_name="demo",
                        goal_summary="Build demo",
                        done_when=["Tests pass"],
                        spec_markdown="# Spec\n",
                        plan_markdown="# Plan\n",
                        tasks=[
                            TaskDraft(
                                slug="foundation",
                                title="Foundation",
                                markdown="# Foundation\n",
                            )
                        ],
                        verification_commands=["python -m unittest"],
                    ),
                ),
                patch("codex_loop.cli.CodexLoopConfig.from_file", return_value=config),
                patch("codex_loop.cli.HookRunner.run") as run_mock,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                run_mock.return_value = [
                    {
                        "success": False,
                        "command": "echo fail",
                        "exit_code": 1,
                        "timed_out": False,
                    }
                ]
                exit_code = main(["init", "--project-dir", str(root), "--prompt", "demo"])

            self.assertEqual(exit_code, 1)
            self.assertIn("post_init", stderr.getvalue())

    def test_status_summary_prints_last_blocker_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "codex-loop.yaml").write_text(
                json.dumps(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                    }
                ),
                encoding="utf-8",
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["status", "--project-dir", str(root), "--summary"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("last_blocker_code: no_progress_limit", stdout.getvalue())
            self.assertIn("last_blocker_reason: Reached no-progress limit.", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
