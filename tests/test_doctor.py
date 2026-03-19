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
            self.assertTrue(any("tasks" in item for item in report.fixed))
            repaired_state = json.loads((root / ".codex-loop" / "state.json").read_text())
            self.assertEqual(repaired_state["tasks"]["001-foundation"]["status"], "done")
            self.assertEqual(repaired_state["tasks"]["003-polish"]["status"], "ready")
            self.assertNotIn("002-old", repaired_state["tasks"])
            schema = json.loads(
                (root / ".codex-loop" / "agent_result.schema.json").read_text()
            )
            self.assertEqual(schema["required"], AGENT_RESULT_SCHEMA["required"])

    def test_repair_adds_missing_operator_defaults_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tasks").mkdir(parents=True)
            (root / "tasks" / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
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

            report = run_doctor(root, repair=True)

            self.assertIn("codex-loop.yaml operator defaults", report.fixed)
            config = json.loads((root / "codex-loop.yaml").read_text(encoding="utf-8"))
            self.assertEqual(config["operator"]["events"]["default_limit"], 20)
            self.assertEqual(config["operator"]["cleanup"]["keep"], 10)

    def test_doctor_reports_invalid_operator_config_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tasks").mkdir(parents=True)
            (root / "tasks" / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
            (root / "codex-loop.yaml").write_text(
                json.dumps(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                        "operator": {"events": {"default_limit": 0}},
                    }
                ),
                encoding="utf-8",
            )

            report = run_doctor(root, repair=False)

            self.assertTrue(report.errors)
            self.assertIn("operator.events.default_limit", report.errors[0])

    def test_doctor_warns_on_aggressive_cleanup_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tasks").mkdir(parents=True)
            (root / "tasks" / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
            (root / "codex-loop.yaml").write_text(
                json.dumps(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                        "operator": {
                            "cleanup": {
                                "keep": 0,
                                "older_than_days": None,
                                "directory_keep": {"logs": 0},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = run_doctor(root, repair=False)

            self.assertTrue(report.warnings)
            self.assertTrue(any("operator.cleanup.keep=0" in item for item in report.warnings))
            self.assertTrue(any("directory_keep.logs=0" in item for item in report.warnings))
            self.assertTrue(any("Suggested remediation" in item for item in report.warnings))

    def test_doctor_warns_when_watchdog_is_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tasks").mkdir(parents=True)
            (root / "tasks" / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
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
            (root / ".codex-loop" / "daemon-watchdog.json").write_text(
                json.dumps(
                    {
                        "phase": "exhausted",
                        "restart_count": 10,
                        "last_restart_reason": "exit_code:2",
                    }
                ),
                encoding="utf-8",
            )

            report = run_doctor(root, repair=False)

            self.assertTrue(
                any("watchdog is exhausted" in item for item in report.warnings)
            )


if __name__ == "__main__":
    unittest.main()
