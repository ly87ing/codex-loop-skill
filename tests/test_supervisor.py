from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_loop.config import CodexLoopConfig
from codex_loop.state_store import StateStore
from codex_loop.supervisor import LoopOutcome, Supervisor
from codex_loop.task_graph import Task, TaskGraph


class StubRunner:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = results

    def run_task(self, *, task: Task, resume_session: str | None) -> dict[str, object]:
        return self.results.pop(0)


class StubVerifier:
    def __init__(self, outcomes: list[bool]) -> None:
        self.outcomes = outcomes

    def run(
        self,
        commands: list[str],
        cwd: Path,
        pass_requires_all: bool = True,
    ) -> tuple[bool, list[dict[str, object]]]:
        return self.outcomes.pop(0), [{"command": commands[0], "exit_code": 1 if not self.outcomes else 0}]


class SupervisorTests(unittest.TestCase):
    def test_blocks_after_repeated_no_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "execution": {
                        "max_iterations": 5,
                        "max_no_progress_iterations": 2,
                    },
                    "verification": {"commands": ["python -m unittest"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            graph = TaskGraph(tasks_dir)
            runner = StubRunner(
                [
                    {
                        "status": "continue",
                        "summary": "No code changes",
                        "files_changed": [],
                        "session_id": "s1",
                    },
                    {
                        "status": "continue",
                        "summary": "Still no changes",
                        "files_changed": [],
                        "session_id": "s1",
                    },
                ]
            )
            verifier = StubVerifier([False, False])

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=graph,
                runner=runner,
                verifier=verifier,
            )
            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.BLOCKED)

    def test_blocks_when_state_has_incomplete_tasks_but_no_selectable_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "verification": {"commands": ["python -m unittest"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            state = store.create_initial("demo", "Build demo", ["001-foundation"])
            state["tasks"]["001-foundation"]["status"] = "pending"
            store.save(state)

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=StubRunner([]),
                verifier=StubVerifier([]),
            )

            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.BLOCKED)


if __name__ == "__main__":
    unittest.main()

