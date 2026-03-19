from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.reporting import (
    build_session_inventory,
    build_evidence_bundle,
    format_snapshots_report,
    format_snapshots_summary,
    format_events_summary,
    format_evidence_report,
    format_events_timeline,
    format_sessions_report,
    load_snapshots_index,
    load_events_timeline,
    summarize_snapshots,
    summarize_events,
)
from codex_loop.state_store import StateStore


class ReportingTests(unittest.TestCase):
    def test_events_timeline_includes_hook_and_blocked_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            hooks_dir = root / ".codex-loop" / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            (hooks_dir / "post_iteration.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-19T00:00:00+00:00",
                        "command": "echo hi",
                        "success": True,
                        "exit_code": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rendered = format_events_timeline(root, limit=10)

            self.assertIn("runner_failure", rendered)
            self.assertIn("hook:post_iteration", rendered)
            self.assertIn("blocked:no_progress_limit", rendered)

    def test_events_timeline_can_filter_and_export_structured_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.record_iteration(
                task_id="002-polish",
                summary="Updated polish layer",
                fingerprint="002|continue",
                files_changed=["src/polish.py"],
                verification_passed=False,
                agent_status="continue",
            )
            hooks_dir = root / ".codex-loop" / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            (hooks_dir / "post_iteration.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-19T00:00:00+00:00",
                        "command": "echo hi",
                        "success": True,
                        "exit_code": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            events = load_events_timeline(
                root,
                limit=10,
                task_id="002-polish",
                event_type="iteration:continue",
            )
            rendered = format_events_timeline(
                root,
                limit=10,
                task_id="002-polish",
                event_type="iteration:continue",
            )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["task_id"], "002-polish")
            self.assertEqual(events[0]["label"], "iteration:continue")
            self.assertIn("iteration:continue", rendered)
            self.assertNotIn("runner_failure", rendered)

    def test_events_timeline_can_filter_by_time_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.record_iteration(
                task_id="002-polish",
                summary="Updated polish layer",
                fingerprint="002|continue",
                files_changed=["src/polish.py"],
                verification_passed=False,
                agent_status="continue",
            )
            state = store.load()
            state["history"][0]["timestamp"] = "2026-03-18T00:00:00+00:00"
            state["history"][1]["timestamp"] = "2026-03-20T00:00:00+00:00"
            store.save(state)

            events = load_events_timeline(
                root,
                limit=10,
                since="2026-03-19T00:00:00+00:00",
                until="2026-03-21T00:00:00+00:00",
            )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["task_id"], "002-polish")

    def test_events_summary_aggregates_by_label_and_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.record_iteration(
                task_id="002-polish",
                summary="Updated polish layer",
                fingerprint="002|continue",
                files_changed=["src/polish.py"],
                verification_passed=False,
                agent_status="continue",
            )

            events = load_events_timeline(root, limit=10)
            summary = summarize_events(events)
            rendered = format_events_summary(events)

            self.assertEqual(summary["total_events"], 2)
            self.assertEqual(summary["by_label"]["runner_failure"], 1)
            self.assertEqual(summary["by_label"]["iteration:continue"], 1)
            self.assertEqual(summary["by_task"]["001-foundation"], 1)
            self.assertEqual(summary["by_task"]["002-polish"], 1)
            self.assertIn("total_events: 2", rendered)
            self.assertIn("iteration:continue: 1", rendered)

    def test_events_summary_tracks_blocker_codes_and_blocked_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )

            events = load_events_timeline(root, limit=10)
            summary = summarize_events(events)
            rendered = format_events_summary(events)

            self.assertEqual(summary["by_blocker_code"]["no_progress_limit"], 1)
            self.assertEqual(summary["blocked_tasks"], ["001-foundation"])
            self.assertIn("by_blocker_code:", rendered)
            self.assertIn("no_progress_limit: 1", rendered)

    def test_events_summary_tracks_latest_blocked_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            store.mark_blocked(
                "002-polish",
                reason="Runner circuit breaker tripped.",
                code="runner_failure_circuit_breaker",
            )
            state = store.load()
            state["history"][-2]["timestamp"] = "2026-03-19T00:00:00+00:00"
            state["history"][-1]["timestamp"] = "2026-03-20T00:00:00+00:00"
            store.save(state)

            summary = summarize_events(load_events_timeline(root, limit=10))
            rendered = format_events_summary(load_events_timeline(root, limit=10))

            self.assertEqual(
                summary["latest_blocked"]["task_id"],
                "002-polish",
            )
            self.assertEqual(
                summary["latest_blocked"]["blocker_code"],
                "runner_failure_circuit_breaker",
            )
            self.assertIn("latest_blocked:", rendered)
            self.assertIn("runner_failure_circuit_breaker", rendered)

    def test_events_summary_tracks_latest_runner_and_verification_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="Runner failed once.",
            )
            store.record_iteration(
                task_id="002-polish",
                summary="Verification failed on pytest.",
                fingerprint="002|continue",
                files_changed=["tests/test_polish.py"],
                verification_passed=False,
                agent_status="continue",
            )
            state = store.load()
            state["history"][-2]["timestamp"] = "2026-03-19T00:00:00+00:00"
            state["history"][-1]["timestamp"] = "2026-03-20T00:00:00+00:00"
            store.save(state)

            summary = summarize_events(load_events_timeline(root, limit=10))
            rendered = format_events_summary(load_events_timeline(root, limit=10))

            self.assertEqual(summary["latest_runner_failure"]["task_id"], "001-foundation")
            self.assertEqual(
                summary["latest_verification_failure"]["task_id"],
                "002-polish",
            )
            self.assertIn("latest_runner_failure:", rendered)
            self.assertIn("latest_verification_failure:", rendered)

    def test_session_inventory_tracks_current_and_latest_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            prompts_dir = root / ".codex-loop" / "prompts"
            logs_dir = root / ".codex-loop" / "logs"
            runs_dir = root / ".codex-loop" / "runs"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)
            runs_dir.mkdir(parents=True, exist_ok=True)
            (prompts_dir / "0001-001-foundation.txt").write_text("prompt 1", encoding="utf-8")
            (logs_dir / "0001-001-foundation.jsonl").write_text("log 1", encoding="utf-8")
            (runs_dir / "001-foundation-last.json").write_text("{}", encoding="utf-8")
            (prompts_dir / "0002-002-polish.txt").write_text("prompt 2", encoding="utf-8")
            (logs_dir / "0002-002-polish.jsonl").write_text("log 2", encoding="utf-8")
            (runs_dir / "002-polish-last.json").write_text("{}", encoding="utf-8")
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
            state["tasks"]["001-foundation"]["status"] = "in_progress"
            state["tasks"]["001-foundation"]["session_id"] = "session-001"
            state["tasks"]["002-polish"]["status"] = "pending"
            store.save(state)

            inventory = build_session_inventory(root)
            rendered = format_sessions_report(root)

            self.assertEqual(inventory["project_name"], "demo")
            self.assertEqual(inventory["current_task"], "001-foundation")
            self.assertEqual(inventory["current_task_session"], "session-001")
            self.assertEqual(inventory["latest_session"]["task_id"], "002-polish")
            self.assertEqual(inventory["latest_session"]["session_id"], "session-002")
            self.assertEqual(
                inventory["latest_session"]["artifacts"]["prompt"],
                str((prompts_dir / "0002-002-polish.txt").resolve()),
            )
            self.assertEqual(
                inventory["latest_session"]["artifacts"]["log"],
                str((logs_dir / "0002-002-polish.jsonl").resolve()),
            )
            self.assertEqual(
                inventory["latest_session"]["artifacts"]["run"],
                str((runs_dir / "002-polish-last.json").resolve()),
            )
            first_task = inventory["tasks"][0]
            self.assertEqual(
                first_task["artifacts"]["prompt"],
                str((prompts_dir / "0001-001-foundation.txt").resolve()),
            )
            self.assertEqual(len(inventory["tasks"]), 2)
            self.assertIn("current_task_session: session-001", rendered)
            self.assertIn("latest_session:", rendered)
            self.assertIn("prompt=", rendered)

    def test_evidence_bundle_collects_prompt_log_and_run_payloads(self) -> None:
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

            evidence = build_evidence_bundle(
                root,
                task_id="001-foundation",
                prompt_lines=1,
                log_lines=1,
                event_limit=5,
            )
            rendered = format_evidence_report(
                root,
                task_id="001-foundation",
                prompt_lines=1,
                log_lines=1,
                event_limit=5,
            )

            self.assertEqual(evidence["task_id"], "001-foundation")
            self.assertEqual(evidence["session_id"], "session-001")
            self.assertEqual(evidence["selection"], "task_id")
            self.assertEqual(evidence["prompt_preview"], "line one")
            self.assertEqual(evidence["log_tail"], "log two")
            self.assertEqual(evidence["status_snapshot"]["overall_status"], "blocked")
            self.assertEqual(evidence["status_snapshot"]["current_task"], "001-foundation")
            self.assertEqual(evidence["session_snapshot"]["task_id"], "001-foundation")
            self.assertEqual(evidence["run_payload"]["summary"], "Foundation run")
            self.assertEqual(evidence["events_summary"]["total_events"], 2)
            self.assertEqual(evidence["events_summary"]["by_blocker_code"]["no_progress_limit"], 1)
            self.assertEqual(len(evidence["recent_events"]), 2)
            self.assertEqual(evidence["recent_events"][-1]["label"], "blocked:no_progress_limit")
            self.assertIn("prompt_preview:", rendered)
            self.assertIn("status_snapshot:", rendered)
            self.assertIn("session_snapshot:", rendered)
            self.assertIn("events_summary:", rendered)
            self.assertIn("recent_events:", rendered)
            self.assertIn("run_payload:", rendered)

    def test_snapshots_index_can_filter_and_render_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir)
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

            latest = load_snapshots_index(snapshot_dir, latest=True)
            filtered = load_snapshots_index(snapshot_dir, task_id="001-foundation")
            rendered = format_snapshots_report(snapshot_dir, latest=True)

            self.assertEqual(len(latest), 1)
            self.assertEqual(latest[0]["task_id"], "002-polish")
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["task_id"], "001-foundation")
            self.assertIn("002-polish", rendered)
            self.assertIn("no_progress_limit", rendered)

    def test_snapshots_summary_tracks_status_task_and_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir)
            snapshots = [
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
                    "task_id": "002-polish",
                    "selection": "latest_session",
                    "session_id": "session-003",
                    "overall_status": "completed",
                    "current_task": "done",
                    "last_blocker_code": None,
                    "snapshot_path": str(snapshot_dir / "three.json"),
                },
            ]
            summary = summarize_snapshots(snapshots)
            rendered = format_snapshots_summary(snapshots)

            self.assertEqual(summary["total_snapshots"], 3)
            self.assertEqual(summary["by_task"]["002-polish"], 2)
            self.assertEqual(summary["by_status"]["blocked"], 1)
            self.assertEqual(summary["by_selection"]["latest_session"], 2)
            self.assertEqual(summary["by_blocker_code"]["no_progress_limit"], 1)
            self.assertEqual(summary["latest_snapshot"]["task_id"], "002-polish")
            self.assertEqual(summary["latest_blocked"]["task_id"], "002-polish")
            self.assertIn("total_snapshots: 3", rendered)
            self.assertIn("by_status:", rendered)
            self.assertIn("no_progress_limit: 1", rendered)


if __name__ == "__main__":
    unittest.main()
