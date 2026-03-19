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
            state = store.load()
            state["tasks"]["001-foundation"]["session_id"] = "session-001"
            store.save(state)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["status", "--project-dir", str(root), "--summary"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("demo", stdout.getvalue())
            self.assertIn("001-foundation", stdout.getvalue())
            self.assertIn("current_task_session: session-001", stdout.getvalue())

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

    def test_events_command_can_render_summary_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.record_iteration(
                task_id="001-foundation",
                summary="Verification failed on pytest.",
                fingerprint="001|continue",
                files_changed=["tests/test_foundation.py"],
                verification_passed=False,
                agent_status="continue",
            )
            store.mark_blocked(
                "002-polish",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "events",
                        "--project-dir",
                        str(root),
                        "--summary",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["total_events"], 3)
            self.assertEqual(payload["by_label"]["runner_failure"], 1)
            self.assertEqual(payload["by_blocker_code"]["no_progress_limit"], 1)
            self.assertEqual(payload["latest_blocked"]["task_id"], "002-polish")
            self.assertEqual(payload["latest_runner_failure"]["task_id"], "001-foundation")
            self.assertEqual(
                payload["latest_verification_failure"]["task_id"],
                "001-foundation",
            )

    def test_sessions_command_can_render_json_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_iteration(
                task_id="001-foundation",
                summary="Foundation iteration.",
                fingerprint="001|continue",
                files_changed=["src/foundation.py"],
                verification_passed=False,
                agent_status="continue",
                session_id="session-001",
            )
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "sessions",
                        "--project-dir",
                        str(root),
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["current_task"], "001-foundation")
            self.assertEqual(payload["current_task_session"], "session-001")
            self.assertEqual(payload["latest_session"]["session_id"], "session-001")

    def test_sessions_command_can_emit_latest_session_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_iteration(
                task_id="001-foundation",
                summary="Foundation iteration.",
                fingerprint="001|continue",
                files_changed=["src/foundation.py"],
                verification_passed=False,
                agent_status="continue",
                session_id="session-001",
            )
            store.record_iteration(
                task_id="002-polish",
                summary="Polish iteration.",
                fingerprint="002|continue",
                files_changed=["src/polish.py"],
                verification_passed=False,
                agent_status="continue",
                session_id="session-002",
            )
            state = store.load()
            state["history"][-2]["timestamp"] = "2026-03-19T00:00:00+00:00"
            state["history"][-1]["timestamp"] = "2026-03-20T00:00:00+00:00"
            store.save(state)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "sessions",
                        "--project-dir",
                        str(root),
                        "--latest",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["task_id"], "002-polish")
            self.assertEqual(payload["session_id"], "session-002")

    def test_sessions_command_can_filter_to_task_and_include_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompts_dir = root / ".codex-loop" / "prompts"
            logs_dir = root / ".codex-loop" / "logs"
            runs_dir = root / ".codex-loop" / "runs"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)
            runs_dir.mkdir(parents=True, exist_ok=True)
            (prompts_dir / "0001-001-foundation.txt").write_text("prompt 1", encoding="utf-8")
            (logs_dir / "0001-001-foundation.jsonl").write_text("log 1", encoding="utf-8")
            (runs_dir / "001-foundation-last.json").write_text("{}", encoding="utf-8")
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_iteration(
                task_id="001-foundation",
                summary="Foundation iteration.",
                fingerprint="001|continue",
                files_changed=["src/foundation.py"],
                verification_passed=False,
                agent_status="continue",
                session_id="session-001",
            )
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "sessions",
                        "--project-dir",
                        str(root),
                        "--task-id",
                        "001-foundation",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["task_id"], "001-foundation")
            self.assertEqual(payload["session_id"], "session-001")
            self.assertEqual(
                payload["artifacts"]["prompt"],
                str((prompts_dir / "0001-001-foundation.txt").resolve()),
            )
            self.assertEqual(
                payload["artifacts"]["log"],
                str((logs_dir / "0001-001-foundation.jsonl").resolve()),
            )
            self.assertEqual(
                payload["artifacts"]["run"],
                str((runs_dir / "001-foundation-last.json").resolve()),
            )

    def test_evidence_command_can_render_json_for_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompts_dir = root / ".codex-loop" / "prompts"
            logs_dir = root / ".codex-loop" / "logs"
            runs_dir = root / ".codex-loop" / "runs"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)
            runs_dir.mkdir(parents=True, exist_ok=True)
            (prompts_dir / "0001-001-foundation.txt").write_text(
                "line one\nline two\n",
                encoding="utf-8",
            )
            (logs_dir / "0001-001-foundation.jsonl").write_text(
                "log one\nlog two\n",
                encoding="utf-8",
            )
            (runs_dir / "001-foundation-last.json").write_text(
                json.dumps({"status": "continue", "summary": "Foundation run"}),
                encoding="utf-8",
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.record_iteration(
                task_id="001-foundation",
                summary="Foundation iteration.",
                fingerprint="001|continue",
                files_changed=["src/foundation.py"],
                verification_passed=False,
                agent_status="continue",
                session_id="session-001",
            )
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "evidence",
                        "--project-dir",
                        str(root),
                        "--task-id",
                        "001-foundation",
                        "--prompt-lines",
                        "1",
                        "--log-lines",
                        "1",
                        "--event-limit",
                        "1",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["task_id"], "001-foundation")
            self.assertEqual(payload["selection"], "task_id")
            self.assertEqual(payload["prompt_preview"], "line one")
            self.assertEqual(payload["log_tail"], "log two")
            self.assertEqual(payload["status_snapshot"]["current_task"], "001-foundation")
            self.assertEqual(payload["session_snapshot"]["task_id"], "001-foundation")
            self.assertEqual(payload["events_summary"]["total_events"], 1)
            self.assertEqual(len(payload["recent_events"]), 1)
            self.assertEqual(payload["recent_events"][0]["label"], "blocked:no_progress_limit")
            self.assertEqual(payload["run_payload"]["summary"], "Foundation run")

    def test_evidence_command_can_write_json_to_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompts_dir = root / ".codex-loop" / "prompts"
            logs_dir = root / ".codex-loop" / "logs"
            runs_dir = root / ".codex-loop" / "runs"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)
            runs_dir.mkdir(parents=True, exist_ok=True)
            (prompts_dir / "0001-001-foundation.txt").write_text("line one\n", encoding="utf-8")
            (logs_dir / "0001-001-foundation.jsonl").write_text("log one\n", encoding="utf-8")
            (runs_dir / "001-foundation-last.json").write_text(
                json.dumps({"status": "continue", "summary": "Foundation run"}),
                encoding="utf-8",
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.record_iteration(
                task_id="001-foundation",
                summary="Foundation iteration.",
                fingerprint="001|continue",
                files_changed=["src/foundation.py"],
                verification_passed=False,
                agent_status="continue",
                session_id="session-001",
            )
            output_path = root / "evidence.json"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "evidence",
                        "--project-dir",
                        str(root),
                        "--task-id",
                        "001-foundation",
                        "--json",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn(str(output_path.resolve()), stdout.getvalue())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["task_id"], "001-foundation")
            self.assertEqual(payload["selection"], "task_id")

    def test_evidence_command_can_write_json_to_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompts_dir = root / ".codex-loop" / "prompts"
            logs_dir = root / ".codex-loop" / "logs"
            runs_dir = root / ".codex-loop" / "runs"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)
            runs_dir.mkdir(parents=True, exist_ok=True)
            (prompts_dir / "0001-001-foundation.txt").write_text("line one\n", encoding="utf-8")
            (logs_dir / "0001-001-foundation.jsonl").write_text("log one\n", encoding="utf-8")
            (runs_dir / "001-foundation-last.json").write_text(
                json.dumps({"status": "continue", "summary": "Foundation run"}),
                encoding="utf-8",
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.record_iteration(
                task_id="001-foundation",
                summary="Foundation iteration.",
                fingerprint="001|continue",
                files_changed=["src/foundation.py"],
                verification_passed=False,
                agent_status="continue",
                session_id="session-001",
            )
            output_dir = root / "snapshots"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "evidence",
                        "--project-dir",
                        str(root),
                        "--task-id",
                        "001-foundation",
                        "--json",
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            snapshot_files = sorted(
                path for path in output_dir.glob("*.json") if path.name != "index.json"
            )
            self.assertEqual(len(snapshot_files), 1)
            self.assertIn("001-foundation", snapshot_files[0].name)
            payload = json.loads(snapshot_files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["task_id"], "001-foundation")
            self.assertEqual(payload["status_snapshot"]["current_task"], "001-foundation")
            index_path = output_dir / "index.json"
            self.assertTrue(index_path.exists())
            index_payload = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(len(index_payload["snapshots"]), 1)
            snapshot_entry = index_payload["snapshots"][0]
            self.assertEqual(snapshot_entry["task_id"], "001-foundation")
            self.assertEqual(snapshot_entry["selection"], "task_id")
            self.assertEqual(snapshot_entry["snapshot_path"], str(snapshot_files[0].resolve()))

    def test_snapshots_command_can_render_json_from_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-19T00:00:00+00:00",
                                "task_id": "001-foundation",
                                "selection": "task_id",
                                "session_id": "session-001",
                                "overall_status": "running",
                                "current_task": "001-foundation",
                                "last_blocker_code": None,
                                "snapshot_path": str(snapshot_dir / "one.json"),
                            },
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--latest",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["task_id"], "002-polish")

    def test_snapshots_command_can_render_summary_json_from_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-19T00:00:00+00:00",
                                "task_id": "001-foundation",
                                "selection": "task_id",
                                "session_id": "session-001",
                                "overall_status": "running",
                                "current_task": "001-foundation",
                                "last_blocker_code": None,
                                "snapshot_path": str(snapshot_dir / "one.json"),
                            },
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--summary",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["total_snapshots"], 2)
            self.assertEqual(payload["by_status"]["blocked"], 1)
            self.assertEqual(payload["latest_snapshot"]["task_id"], "002-polish")

    def test_snapshots_command_can_render_grouped_summary_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-19T00:00:00+00:00",
                                "task_id": "001-foundation",
                                "selection": "task_id",
                                "session_id": "session-001",
                                "overall_status": "running",
                                "current_task": "001-foundation",
                                "last_blocker_code": None,
                                "snapshot_path": str(snapshot_dir / "one.json"),
                            },
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--summary",
                        "--group-by",
                        "blocker",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["group_by"], "blocker")
            self.assertEqual(payload["grouped_counts"]["none"], 1)
            self.assertEqual(payload["grouped_counts"]["no_progress_limit"], 1)

    def test_snapshots_command_rejects_group_by_without_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps({"snapshots": []}),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--group-by",
                        "task",
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("Use --group-by only with --summary", stderr.getvalue())

    def test_snapshots_command_can_filter_by_status_and_time_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-19T00:00:00+00:00",
                                "task_id": "001-foundation",
                                "selection": "task_id",
                                "session_id": "session-001",
                                "overall_status": "running",
                                "current_task": "001-foundation",
                                "last_blocker_code": None,
                                "snapshot_path": str(snapshot_dir / "one.json"),
                            },
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            },
                            {
                                "generated_at": "2026-03-21T00:00:00+00:00",
                                "task_id": "003-release",
                                "selection": "latest_session",
                                "session_id": "session-003",
                                "overall_status": "blocked",
                                "current_task": "003-release",
                                "last_blocker_code": "runner_failure_limit",
                                "snapshot_path": str(snapshot_dir / "three.json"),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--status",
                        "blocked",
                        "--since",
                        "2026-03-20T00:00:00+00:00",
                        "--until",
                        "2026-03-20T23:59:59+00:00",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["task_id"], "002-polish")

    def test_snapshots_command_can_filter_by_blocker_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            },
                            {
                                "generated_at": "2026-03-21T00:00:00+00:00",
                                "task_id": "003-release",
                                "selection": "latest_session",
                                "session_id": "session-003",
                                "overall_status": "blocked",
                                "current_task": "003-release",
                                "last_blocker_code": "runner_failure_limit",
                                "snapshot_path": str(snapshot_dir / "three.json"),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--blocker-code",
                        "runner_failure_limit",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["task_id"], "003-release")

    def test_snapshots_command_can_write_json_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output_path = Path(tmpdir) / "snapshots.json"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--json",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["task_id"], "002-polish")
            self.assertIn("Wrote snapshots to", stdout.getvalue())

    def test_snapshots_command_can_write_summary_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output_path = Path(tmpdir) / "snapshots.txt"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--summary",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(output_path.exists())
            rendered = output_path.read_text(encoding="utf-8")
            self.assertIn("total_snapshots: 1", rendered)
            self.assertIn("by_blocker_code:", rendered)
            self.assertIn("Wrote snapshots to", stdout.getvalue())

    def test_snapshots_command_can_write_json_to_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output_dir = Path(tmpdir) / "snapshot-exports"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--json",
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            export_files = sorted(output_dir.glob("snapshots-*.json"))
            self.assertEqual(len(export_files), 1)
            payload = json.loads(export_files[0].read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["task_id"], "002-polish")
            manifest_path = output_dir / "manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["exports"]), 1)
            export_entry = manifest["exports"][0]
            self.assertEqual(export_entry["summary"], False)
            self.assertEqual(export_entry["render_format"], "json")
            self.assertEqual(export_entry["snapshot_count"], 1)
            self.assertEqual(export_entry["source_snapshot_dir"], str(snapshot_dir.resolve()))
            self.assertEqual(export_entry["export_path"], str(export_files[0].resolve()))
            self.assertIn("Wrote snapshots to", stdout.getvalue())

    def test_snapshots_command_can_write_summary_to_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output_dir = Path(tmpdir) / "snapshot-exports"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--summary",
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            export_files = sorted(output_dir.glob("snapshots-*.txt"))
            self.assertEqual(len(export_files), 1)
            rendered = export_files[0].read_text(encoding="utf-8")
            self.assertIn("total_snapshots: 1", rendered)
            manifest_path = output_dir / "manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["exports"]), 1)
            export_entry = manifest["exports"][0]
            self.assertEqual(export_entry["summary"], True)
            self.assertEqual(export_entry["render_format"], "text")
            self.assertEqual(export_entry["snapshot_count"], 1)
            self.assertEqual(export_entry["export_path"], str(export_files[0].resolve()))
            self.assertIn("Wrote snapshots to", stdout.getvalue())

    def test_snapshots_command_rejects_output_and_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps({"snapshots": []}),
                encoding="utf-8",
            )
            output_dir = Path(tmpdir) / "snapshot-exports"
            output_path = Path(tmpdir) / "snapshots.json"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--output",
                        str(output_path),
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("Use either --output or --output-dir", stderr.getvalue())

    def test_snapshots_command_can_sort_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-19T00:00:00+00:00",
                                "task_id": "001-foundation",
                                "selection": "task_id",
                                "session_id": "session-001",
                                "overall_status": "running",
                                "current_task": "001-foundation",
                                "last_blocker_code": None,
                                "snapshot_path": str(snapshot_dir / "one.json"),
                            },
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--sort",
                        "newest",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload), 2)
            self.assertEqual(payload[0]["task_id"], "002-polish")

    def test_snapshots_command_can_select_latest_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "generated_at": "2026-03-19T00:00:00+00:00",
                                "task_id": "001-foundation",
                                "selection": "task_id",
                                "session_id": "session-001",
                                "overall_status": "blocked",
                                "current_task": "001-foundation",
                                "last_blocker_code": "no_progress_limit",
                                "snapshot_path": str(snapshot_dir / "one.json"),
                            },
                            {
                                "generated_at": "2026-03-20T00:00:00+00:00",
                                "task_id": "002-polish",
                                "selection": "latest_session",
                                "session_id": "session-002",
                                "overall_status": "blocked",
                                "current_task": "002-polish",
                                "last_blocker_code": "runner_failure_limit",
                                "snapshot_path": str(snapshot_dir / "two.json"),
                            },
                            {
                                "generated_at": "2026-03-21T00:00:00+00:00",
                                "task_id": "003-release",
                                "selection": "latest_session",
                                "session_id": "session-003",
                                "overall_status": "completed",
                                "current_task": "done",
                                "last_blocker_code": None,
                                "snapshot_path": str(snapshot_dir / "three.json"),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--latest-blocked",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["task_id"], "002-polish")

    def test_snapshots_command_rejects_latest_and_latest_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "index.json").write_text(
                json.dumps({"snapshots": []}),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots",
                        "--snapshot-dir",
                        str(snapshot_dir),
                        "--latest",
                        "--latest-blocked",
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("Use either --latest or --latest-blocked", stderr.getvalue())

    def test_snapshots_exports_command_can_render_latest_json_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            exports_dir = Path(tmpdir) / "snapshot-reports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            (exports_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "exports": [
                            {
                                "generated_at": "2026-03-21T00:00:00+00:00",
                                "export_path": str(exports_dir / "snapshots-list-a.json"),
                                "source_snapshot_dir": str(exports_dir / "source-a"),
                                "snapshot_count": 1,
                                "summary": False,
                                "group_by": None,
                                "render_format": "json",
                                "filters": {
                                    "task_id": "001-foundation",
                                    "status": None,
                                    "blocker_code": None,
                                    "latest": False,
                                    "latest_blocked": False,
                                    "sort_order": "oldest",
                                    "since": None,
                                    "until": None,
                                },
                            },
                            {
                                "generated_at": "2026-03-22T00:00:00+00:00",
                                "export_path": str(exports_dir / "snapshots-summary-b.txt"),
                                "source_snapshot_dir": str(exports_dir / "source-b"),
                                "snapshot_count": 2,
                                "summary": True,
                                "group_by": "status",
                                "render_format": "text",
                                "filters": {
                                    "task_id": None,
                                    "status": "blocked",
                                    "blocker_code": "no_progress_limit",
                                    "latest": False,
                                    "latest_blocked": True,
                                    "sort_order": "newest",
                                    "since": "2026-03-22T00:00:00+00:00",
                                    "until": None,
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "snapshots-exports",
                        "--exports-dir",
                        str(exports_dir),
                        "--latest",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["render_format"], "text")
            self.assertEqual(payload[0]["export_path"], str(exports_dir / "snapshots-summary-b.txt"))

    def test_events_command_uses_config_default_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "codex-loop.yaml").write_text(
                json.dumps(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                        "operator": {"events": {"default_limit": 7}},
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch("codex_loop.cli.load_events_timeline", return_value=[] ) as events_mock,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = main(["events", "--project-dir", str(root), "--json"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            events_mock.assert_called_once()
            self.assertEqual(events_mock.call_args.kwargs["limit"], 7)

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

    def test_cleanup_command_uses_config_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "codex-loop.yaml").write_text(
                json.dumps(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                        "operator": {
                            "cleanup": {
                                "keep": 6,
                                "older_than_days": 14,
                                "directory_keep": {"logs": 20},
                                "directory_older_than_days": {"prompts": 30},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
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
                exit_code = main(["cleanup", "--project-dir", str(root)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            cleanup_mock.assert_called_once_with(
                root.resolve(),
                apply=False,
                keep=6,
                older_than_days=14,
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
