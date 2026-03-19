from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.doctor import run_doctor
from codex_loop.init_flow import AGENT_RESULT_SCHEMA
from codex_loop.state_store import StateStore


class DoctorTests(unittest.TestCase):
    def test_repair_restores_schema_and_reconciles_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tasks").mkdir(parents=True)
            (root / "tasks" / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
            (root / "tasks" / "003-polish.md").write_text("# Polish\n\nShip it.\n")
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
            state = store.create_initial("demo", "Build demo", ["001-foundation", "002-old"])
            state["tasks"]["001-foundation"]["status"] = "done"
            store.save(state)

            report = run_doctor(root, repair=True)

            self.assertTrue(report.fixed)
            self.assertIn(".codex-loop/agent_result.schema.json", report.fixed)
            self.assertIn("tasks", report.fixed[1])
            repaired_state = json.loads((root / ".codex-loop" / "state.json").read_text())
            self.assertEqual(repaired_state["tasks"]["001-foundation"]["status"], "done")
            self.assertEqual(repaired_state["tasks"]["003-polish"]["status"], "ready")
            self.assertNotIn("002-old", repaired_state["tasks"])
            schema = json.loads(
                (root / ".codex-loop" / "agent_result.schema.json").read_text()
            )
            self.assertEqual(schema["required"], AGENT_RESULT_SCHEMA["required"])


if __name__ == "__main__":
    unittest.main()
