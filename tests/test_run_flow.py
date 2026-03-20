from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.run_flow import run_project_continuously
from codex_loop.state_store import StateStore
from codex_loop.supervisor import LoopOutcome


class RunFlowTests(unittest.TestCase):
    def test_continuous_run_requeues_blocked_state_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )

            observed_statuses: list[str] = []

            def fake_run_once(project_dir: Path) -> LoopOutcome:
                state = StateStore(project_dir / ".codex-loop" / "state.json").load()
                observed_statuses.append(state["tasks"]["001-foundation"]["status"])
                return LoopOutcome.COMPLETED

            outcome = run_project_continuously(
                root,
                retry_blocked=True,
                max_cycles=1,
                cycle_sleep_seconds=0.0,
                sleep_fn=lambda _seconds: None,
                run_once=fake_run_once,
            )

            self.assertEqual(outcome, LoopOutcome.COMPLETED)
            self.assertEqual(observed_statuses, ["ready"])

    def test_continuous_run_stops_after_max_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])

            calls: list[int] = []
            sleeps: list[float] = []

            def fake_run_once(_project_dir: Path) -> LoopOutcome:
                calls.append(1)
                return LoopOutcome.BLOCKED

            outcome = run_project_continuously(
                root,
                retry_blocked=True,
                max_cycles=2,
                cycle_sleep_seconds=3.5,
                sleep_fn=sleeps.append,
                run_once=fake_run_once,
            )

            self.assertEqual(outcome, LoopOutcome.BLOCKED)
            self.assertEqual(len(calls), 2)
            self.assertEqual(sleeps, [3.5])

    def test_continuous_run_can_retry_runtime_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])

            calls: list[int] = []
            sleeps: list[float] = []
            heartbeat_path = root / ".codex-loop" / "daemon-heartbeat.json"

            def fake_run_once(_project_dir: Path) -> LoopOutcome:
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("transient runner crash")
                return LoopOutcome.COMPLETED

            outcome = run_project_continuously(
                root,
                retry_blocked=True,
                retry_errors=True,
                max_error_retries=2,
                cycle_sleep_seconds=2.0,
                heartbeat_path=heartbeat_path,
                sleep_fn=sleeps.append,
                run_once=fake_run_once,
            )

            self.assertEqual(outcome, LoopOutcome.COMPLETED)
            self.assertEqual(len(calls), 2)
            self.assertEqual(sleeps, [2.0])
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["phase"], "completed")
            self.assertEqual(heartbeat["outcome"], "completed")
            self.assertEqual(heartbeat["error_count"], 1)


    def test_continuous_run_retries_value_errors(self) -> None:
        # ValueError (e.g. from corrupted YAML config) must be retried
        # when retry_errors=True, same as RuntimeError.
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])

            calls: list[int] = []

            def fake_run_once(_project_dir: Path) -> LoopOutcome:
                calls.append(1)
                if len(calls) == 1:
                    raise ValueError("Invalid YAML configuration: mapping values are not allowed here")
                return LoopOutcome.COMPLETED

            outcome = run_project_continuously(
                root,
                retry_blocked=False,
                retry_errors=True,
                max_error_retries=2,
                cycle_sleep_seconds=0.0,
                sleep_fn=lambda _: None,
                run_once=fake_run_once,
            )

            self.assertEqual(outcome, LoopOutcome.COMPLETED)
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
