from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.state_store import StateStore


class StateStoreTests(unittest.TestCase):
    def test_records_progress_and_detects_no_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial(
                project_name="demo",
                source_prompt="Build it",
                tasks=["001-foundation", "002-loop"],
            )

            store.record_iteration(
                task_id="001-foundation",
                summary="Changed files",
                fingerprint="abc",
                files_changed=["src/a.py"],
                verification_passed=False,
                agent_status="continue",
            )
            store.record_iteration(
                task_id="001-foundation",
                summary="No changes",
                fingerprint="abc",
                files_changed=[],
                verification_passed=False,
                agent_status="continue",
            )

            state = json.loads((root / ".codex-loop" / "state.json").read_text())
            self.assertEqual(state["meta"]["iteration"], 2)
            self.assertEqual(state["meta"]["no_progress_iterations"], 1)
            self.assertEqual(state["tasks"]["001-foundation"]["status"], "in_progress")

    def test_reconciles_task_state_with_task_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            state = store.create_initial(
                project_name="demo",
                source_prompt="Build it",
                tasks=["001-foundation", "002-loop"],
            )
            state["tasks"]["001-foundation"]["status"] = "done"
            store.save(state)

            updated = store.reconcile_tasks(["001-foundation", "003-polish"])

            self.assertEqual(updated["tasks"]["001-foundation"]["status"], "done")
            self.assertEqual(updated["tasks"]["003-polish"]["status"], "ready")
            self.assertNotIn("002-loop", updated["tasks"])
            self.assertEqual(
                updated["meta"]["archived_tasks"]["002-loop"]["status"],
                "pending",
            )

    def test_persists_structured_blocker_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial(
                project_name="demo",
                source_prompt="Build it",
                tasks=["001-foundation"],
            )

            state = store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )

            self.assertEqual(state["tasks"]["001-foundation"]["blocker_code"], "no_progress_limit")
            self.assertEqual(state["meta"]["last_blocker"]["code"], "no_progress_limit")
            self.assertEqual(state["history"][-1]["event_type"], "blocked")
            self.assertEqual(state["history"][-1]["blocker_code"], "no_progress_limit")

    def test_can_requeue_blocked_tasks_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            state = store.create_initial(
                project_name="demo",
                source_prompt="Build it",
                tasks=["001-foundation", "002-loop"],
            )
            state["meta"]["no_progress_iterations"] = 3
            state["meta"]["consecutive_runner_failures"] = 2
            state["meta"]["consecutive_verification_failures"] = 1
            store.save(state)
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )

            updated = store.requeue_blocked_tasks()

            self.assertEqual(updated["tasks"]["001-foundation"]["status"], "ready")
            self.assertIsNone(updated["tasks"]["001-foundation"]["blocker_code"])
            self.assertIsNone(updated["tasks"]["001-foundation"]["blocker_reason"])
            self.assertEqual(updated["tasks"]["002-loop"]["status"], "pending")
            self.assertEqual(updated["meta"]["overall_status"], "running")
            self.assertEqual(updated["meta"]["no_progress_iterations"], 0)
            self.assertEqual(updated["meta"]["consecutive_runner_failures"], 0)
            self.assertEqual(updated["meta"]["consecutive_verification_failures"], 0)
            self.assertIsNone(updated["meta"]["last_blocker"])
            self.assertEqual(updated["history"][-1]["event_type"], "requeued")
            self.assertEqual(updated["history"][-1]["task_id"], "001-foundation")

    def test_records_watchdog_events_and_updates_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial(
                project_name="demo",
                source_prompt="Build it",
                tasks=["001-foundation"],
            )

            state = store.record_watchdog_event(
                event_type="watchdog_restart",
                summary="Restarting worker after stale heartbeat.",
                restart_reason="stale_heartbeat",
                restart_count=1,
                child_pid=4321,
            )
            store.record_watchdog_event(
                event_type="watchdog_exhausted",
                summary="Watchdog exhausted restart budget after repeated crashes.",
                restart_reason="exit_code:2",
                restart_count=10,
                child_pid=4321,
                child_exit_code=2,
            )

            self.assertEqual(state["history"][-1]["event_type"], "watchdog_restart")
            self.assertEqual(state["history"][-1]["restart_reason"], "stale_heartbeat")
            state = json.loads((root / ".codex-loop" / "state.json").read_text())
            self.assertEqual(state["history"][-1]["event_type"], "watchdog_exhausted")
            self.assertEqual(state["history"][-1]["restart_reason"], "exit_code:2")
            self.assertEqual(state["history"][-1]["child_exit_code"], 2)

            metrics = json.loads((root / ".codex-loop" / "metrics.json").read_text())
            self.assertEqual(metrics["watchdog_restarts_total"], 1)
            self.assertEqual(metrics["watchdog_exhausted_total"], 1)
            self.assertEqual(metrics["watchdog_restart_reasons"]["stale_heartbeat"], 1)
            self.assertEqual(metrics["watchdog_restart_reasons"]["exit_code:2"], 1)
            self.assertEqual(metrics["latest_watchdog_exhausted"]["child_exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
