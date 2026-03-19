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


if __name__ == "__main__":
    unittest.main()
