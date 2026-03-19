from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.init_flow import InitResult, TaskDraft, initialize_project


class InitializeProjectTests(unittest.TestCase):
    def test_initialize_project_writes_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            result = InitResult(
                project_name="demo-service",
                goal_summary="Build a local autonomous loop.",
                done_when=["Tests pass", "Tasks are marked complete"],
                spec_markdown="# Demo Spec\n\nThe goal is clear.\n",
                plan_markdown="# Demo Plan\n\n1. Build it.\n",
                tasks=[
                    TaskDraft(
                        slug="foundation",
                        title="Foundation",
                        markdown="# Foundation\n\nCreate the skeleton.\n",
                    ),
                    TaskDraft(
                        slug="execution-loop",
                        title="Execution Loop",
                        markdown="# Execution Loop\n\nImplement the loop.\n",
                    ),
                ],
                verification_commands=["python -m unittest discover -s tests"],
            )

            initialize_project(
                project_dir=project_dir,
                prompt="Build me a loop",
                result=result,
                force=False,
            )

            config = json.loads((project_dir / "codex-loop.yaml").read_text())
            self.assertEqual(config["project"]["name"], "demo-service")
            self.assertEqual(
                config["verification"]["commands"],
                ["python -m unittest discover -s tests"],
            )
            self.assertTrue((project_dir / "spec" / "001-project-spec.md").exists())
            self.assertTrue(
                (project_dir / "plan" / "001-implementation-plan.md").exists()
            )
            self.assertTrue((project_dir / "tasks" / "001-foundation.md").exists())
            self.assertTrue(
                (project_dir / "tasks" / "002-execution-loop.md").exists()
            )
            state = json.loads((project_dir / ".codex-loop" / "state.json").read_text())
            metrics = json.loads(
                (project_dir / ".codex-loop" / "metrics.json").read_text()
            )
            self.assertEqual(state["meta"]["source_prompt"], "Build me a loop")
            self.assertEqual(state["tasks"]["001-foundation"]["status"], "ready")
            self.assertEqual(state["tasks"]["002-execution-loop"]["status"], "pending")
            self.assertEqual(metrics["tasks_total"], 2)
            self.assertEqual(metrics["total_iterations"], 0)


if __name__ == "__main__":
    unittest.main()
