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


    def test_save_succeeds_even_if_metrics_write_fails(self) -> None:
        """state.json save must not raise when metrics.json write fails."""
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            state = store.create_initial(
                project_name="demo",
                source_prompt="Build it",
                tasks=["001-foundation"],
            )
            with patch(
                "codex_loop.state_store.write_metrics_snapshot",
                side_effect=OSError("disk full"),
            ):
                store.save(state)  # must not raise

            saved = json.loads((root / ".codex-loop" / "state.json").read_text())
            self.assertIn("001-foundation", saved["tasks"])


    def test_record_iteration_preserves_session_id_when_none_passed(self) -> None:
        """record_iteration must not overwrite an existing session_id with None.
        If the runner doesn't return a session_id in a given iteration, the
        previously saved session_id must be kept for resume to work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build it", ["001-task"])

            # First iteration establishes a session_id.
            store.record_iteration(
                task_id="001-task",
                summary="initial",
                fingerprint="fp1",
                files_changed=["a.py"],
                verification_passed=True,
                agent_status="continue",
                session_id="session-abc",
            )
            state = store.load()
            self.assertEqual(state["tasks"]["001-task"]["session_id"], "session-abc")

            # Second iteration passes session_id=None (agent didn't echo it back).
            store.record_iteration(
                task_id="001-task",
                summary="follow-up",
                fingerprint="fp2",
                files_changed=["b.py"],
                verification_passed=True,
                agent_status="continue",
                session_id=None,
            )
            state = store.load()
            # session_id must still be the original value.
            self.assertEqual(state["tasks"]["001-task"]["session_id"], "session-abc")


    def test_transient_runner_failure_does_not_increment_no_progress(self) -> None:
        """Transient errors (network, timeout, kill) are infrastructure blips and must
        not advance the no_progress_iterations counter, which would wrongly trigger
        the no_progress_limit circuit breaker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial(
                project_name="demo",
                source_prompt="Build it",
                tasks=["001-foundation"],
            )

            store.record_runner_failure(
                task_id="001-foundation",
                reason="connection reset by peer",
                transient=True,
            )
            state = store.load()
            self.assertEqual(state["meta"]["no_progress_iterations"], 0)
            self.assertEqual(state["meta"]["consecutive_runner_failures"], 0)

            # Non-transient failure DOES increment both counters.
            store.record_runner_failure(
                task_id="001-foundation",
                reason="codex command failed with exit code 1",
                transient=False,
            )
            state = store.load()
            self.assertEqual(state["meta"]["no_progress_iterations"], 1)
            self.assertEqual(state["meta"]["consecutive_runner_failures"], 1)


if __name__ == "__main__":
    unittest.main()
