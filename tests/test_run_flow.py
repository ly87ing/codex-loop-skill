from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
