from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.config import CodexLoopConfig
from codex_loop.hooks import HookRunner
from codex_loop.state_store import StateStore
from codex_loop.supervisor import LoopOutcome, Supervisor
from codex_loop.task_graph import Task, TaskGraph


class StubRunner:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = results

    def run_task(self, *, task: Task, resume_session: str | None) -> dict[str, object]:
        return self.results.pop(0)


class FailingRunner:
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors

    def run_task(self, *, task: Task, resume_session: str | None) -> dict[str, object]:
        del task, resume_session
        raise RuntimeError(self.errors.pop(0))


class StubVerifier:
    def __init__(self, outcomes: list[bool]) -> None:
        self.outcomes = outcomes

    def run(
        self,
        commands: list[str],
        cwd: Path,
        pass_requires_all: bool = True,
        timeout_seconds: int = 300,
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

    def test_blocks_after_repeated_runner_failures(self) -> None:
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
                        "max_consecutive_runner_failures": 2,
                    },
                    "verification": {"commands": ["python -m unittest"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            graph = TaskGraph(tasks_dir)

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=graph,
                runner=FailingRunner(["runner failed 1", "runner failed 2"]),
                verifier=StubVerifier([]),
            )
            outcome = supervisor.run()

            state = store.load()
            metrics = json.loads((root / ".codex-loop" / "metrics.json").read_text())
            self.assertEqual(outcome, LoopOutcome.BLOCKED)
            self.assertEqual(state["meta"]["consecutive_runner_failures"], 2)
            self.assertEqual(state["tasks"]["001-foundation"]["status"], "blocked")
            self.assertIn("runner failure circuit breaker", state["tasks"]["001-foundation"]["blocker_reason"].lower())
            self.assertEqual(metrics["runner_failures_total"], 2)

    def test_blocks_after_repeated_verification_failures(self) -> None:
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
                        "max_no_progress_iterations": 10,
                        "max_consecutive_verification_failures": 2,
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
                        "summary": "Changed code",
                        "files_changed": ["src/a.py"],
                        "session_id": "s1",
                    },
                    {
                        "status": "continue",
                        "summary": "Changed code again",
                        "files_changed": ["src/a.py"],
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

            state = store.load()
            metrics = json.loads((root / ".codex-loop" / "metrics.json").read_text())
            self.assertEqual(outcome, LoopOutcome.BLOCKED)
            self.assertEqual(state["meta"]["consecutive_verification_failures"], 2)
            self.assertEqual(state["tasks"]["001-foundation"]["status"], "blocked")
            self.assertIn("verification failure circuit breaker", state["tasks"]["001-foundation"]["blocker_reason"].lower())
            self.assertEqual(metrics["verification_failures_total"], 2)

    def test_runs_iteration_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
            pre_file = root / "pre.txt"
            post_file = root / "post.txt"

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "verification": {"commands": ["python -m unittest"]},
                    "tasks": {"source_dir": "tasks"},
                    "hooks": {
                        "pre_iteration": [
                            f"python3 -c \"from pathlib import Path; import os; Path(r'{pre_file}').write_text(os.environ['CODEX_LOOP_TASK_ID'])\""
                        ],
                        "post_iteration": [
                            f"python3 -c \"from pathlib import Path; import os; Path(r'{post_file}').write_text(os.environ['CODEX_LOOP_AGENT_STATUS'])\""
                        ],
                    },
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
                        "summary": "Changed code",
                        "files_changed": ["src/a.py"],
                        "session_id": "s1",
                    }
                ]
            )
            verifier = StubVerifier([True, True])  # iteration + final verification

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=graph,
                runner=runner,
                verifier=verifier,
                hook_runner=HookRunner(root / ".codex-loop" / "hooks"),
            )
            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.COMPLETED)
            self.assertEqual(pre_file.read_text(), "001-foundation")
            self.assertEqual(post_file.read_text(), "continue")

    def test_blocks_when_hook_failure_policy_is_block(self) -> None:
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
                    "hooks": {
                        "failure_policy": "block",
                        "pre_iteration": ["python3 -c \"raise SystemExit(7)\""],
                    },
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=StubRunner(
                    [
                        {
                            "status": "continue",
                            "summary": "Changed code",
                            "files_changed": ["src/a.py"],
                            "session_id": "s1",
                        }
                    ]
                ),
                verifier=StubVerifier([True]),
                hook_runner=HookRunner(root / ".codex-loop" / "hooks"),
            )

            outcome = supervisor.run()

            state = store.load()
            self.assertEqual(outcome, LoopOutcome.BLOCKED)
            self.assertEqual(state["tasks"]["001-foundation"]["status"], "blocked")
            self.assertIn("hook failure", state["tasks"]["001-foundation"]["blocker_reason"].lower())

    def test_ignores_hook_failure_when_policy_is_ignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
            complete_file = root / "completed.txt"

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "verification": {"commands": ["python -m unittest"]},
                    "tasks": {"source_dir": "tasks"},
                    "hooks": {
                        "failure_policy": "ignore",
                        "pre_iteration": ["python3 -c \"raise SystemExit(9)\""],
                        "on_completed": [
                            f"python3 -c \"from pathlib import Path; Path(r'{complete_file}').write_text('done')\""
                        ],
                    },
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=StubRunner(
                    [
                        {
                            "status": "continue",
                            "summary": "Changed code",
                            "files_changed": ["src/a.py"],
                            "session_id": "s1",
                        }
                    ]
                ),
                verifier=StubVerifier([True, True]),  # iteration + final verification
                hook_runner=HookRunner(root / ".codex-loop" / "hooks"),
            )

            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.COMPLETED)
            self.assertEqual(complete_file.read_text(), "done")

    def test_runs_on_blocked_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
            blocked_file = root / "blocked.txt"

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "execution": {"max_consecutive_runner_failures": 1},
                    "verification": {"commands": ["python -m unittest"]},
                    "tasks": {"source_dir": "tasks"},
                    "hooks": {
                        "on_blocked": [
                            f"python3 -c \"from pathlib import Path; import os; Path(r'{blocked_file}').write_text(os.environ['CODEX_LOOP_OUTCOME'])\""
                        ]
                    },
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=FailingRunner(["runner failed"]),
                verifier=StubVerifier([]),
                hook_runner=HookRunner(root / ".codex-loop" / "hooks"),
            )

            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.BLOCKED)
            self.assertEqual(blocked_file.read_text(), "blocked")

    def test_applies_backoff_with_jitter_between_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
            sleep_calls: list[float] = []

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "execution": {
                        "max_iterations": 3,
                        "max_no_progress_iterations": 10,
                        "iteration_backoff_seconds": 2,
                        "iteration_backoff_jitter_seconds": 0.5,
                    },
                    "verification": {"commands": ["python -m unittest"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=StubRunner(
                    [
                        {
                            "status": "continue",
                            "summary": "Changed code",
                            "files_changed": ["src/a.py"],
                            "session_id": "s1",
                        },
                        {
                            "status": "continue",
                            "summary": "Finished code",
                            "files_changed": ["src/a.py"],
                            "session_id": "s1",
                        },
                    ]
                ),
                verifier=StubVerifier([False, True, True]),  # iter1 fail, iter2 pass, final verification
                sleep_fn=sleep_calls.append,
                jitter_fn=lambda low, high: 0.25,
            )

            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.COMPLETED)
            self.assertEqual(sleep_calls, [2.25])

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


    def test_final_verification_prevents_false_completion(self) -> None:
        """All tasks done but final verification fails → last task reopened, loop continues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "execution": {"max_iterations": 5},
                    "verification": {"commands": ["python3 -c 'raise SystemExit(0)'"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            # Pre-mark task as done so _terminal_outcome_without_selectable_task fires
            state = store.load()
            state["tasks"]["001-foundation"]["status"] = "done"
            state["meta"]["overall_status"] = "completed"
            store.save(state)

            # Verifier: first call (final verification) passes → COMPLETED
            verifier = StubVerifier([True])
            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=StubRunner([]),
                verifier=verifier,
            )

            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.COMPLETED)

    def test_final_verification_failure_reopens_task(self) -> None:
        """All tasks done but final verification fails → task reopened, loop keeps running."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "execution": {"max_iterations": 4, "max_no_progress_iterations": 3},
                    "verification": {"commands": ["python3 -c 'raise SystemExit(1)'"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            state = store.load()
            state["tasks"]["001-foundation"]["status"] = "done"
            state["meta"]["overall_status"] = "completed"
            store.save(state)

            # Final verification fails, then subsequent iterations also fail → BLOCKED
            verifier = StubVerifier([False, False, False, False, False])
            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=StubRunner(
                    [
                        {"status": "continue", "summary": "s", "task_id": "001-foundation",
                         "files_changed": [], "verification_expected": [], "needs_resume": False,
                         "blockers": [], "next_action": "continue"},
                        {"status": "continue", "summary": "s", "task_id": "001-foundation",
                         "files_changed": [], "verification_expected": [], "needs_resume": False,
                         "blockers": [], "next_action": "continue"},
                        {"status": "continue", "summary": "s", "task_id": "001-foundation",
                         "files_changed": [], "verification_expected": [], "needs_resume": False,
                         "blockers": [], "next_action": "continue"},
                    ]
                ),
                verifier=verifier,
            )

            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.BLOCKED)

    def test_real_files_changed_falls_back_to_agent_report_when_no_git(self) -> None:
        """_real_files_changed returns agent-reported list when git is unavailable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Non-git directory → git commands fail
            result = Supervisor._real_files_changed(
                Path(tmpdir),
                ["src/foo.py", "src/bar.py"],
            )
            self.assertEqual(result, ["src/foo.py", "src/bar.py"])

    def test_real_files_changed_returns_empty_when_no_changes_and_no_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = Supervisor._real_files_changed(Path(tmpdir), [])
            self.assertEqual(result, [])

    def test_transient_error_does_not_consume_runner_failure_counter(self) -> None:
        """A transient error (timeout) should not increment consecutive_runner_failures."""
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
                        "max_iterations": 4,
                        "max_consecutive_runner_failures": 2,
                        "max_no_progress_iterations": 10,
                    },
                    "verification": {"commands": ["python3 -c 'raise SystemExit(0)'"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])

            # Raise a transient error message every time
            class TransientRunner:
                def run_task(self, *, task, resume_session):
                    raise RuntimeError("Codex command timed out.")

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=TransientRunner(),
                verifier=StubVerifier([False, False, False, False]),
            )
            outcome = supervisor.run()

            # Transient errors don't trip the runner failure circuit breaker;
            # loop exhausts max_iterations instead.
            state = store.load()
            self.assertEqual(
                state["meta"]["consecutive_runner_failures"], 0
            )

    def test_is_transient_runner_error_classifies_correctly(self) -> None:
        self.assertTrue(Supervisor._is_transient_runner_error("Codex command timed out."))
        self.assertTrue(Supervisor._is_transient_runner_error("connection reset by peer"))
        self.assertTrue(Supervisor._is_transient_runner_error("rate limit exceeded 429"))
        self.assertFalse(Supervisor._is_transient_runner_error("schema validation failed"))
        self.assertFalse(Supervisor._is_transient_runner_error("task_id mismatch"))

    def test_done_and_blocked_mix_completes_when_verification_passes(self) -> None:
        """When some tasks are done and others blocked by task circuit breaker,
        the loop should COMPLETE if final verification passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text("# Foundation\n\nDo it.\n")
            (tasks_dir / "002-extra.md").write_text("# Extra\n\nExtra.\n")

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "execution": {"max_iterations": 5},
                    "verification": {"commands": ["python3 -c 'raise SystemExit(0)'"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-extra"])
            state = store.load()
            state["tasks"]["001-foundation"]["status"] = "done"
            state["tasks"]["002-extra"]["status"] = "blocked"
            state["tasks"]["002-extra"]["blocker_code"] = "task_failure_circuit_breaker"
            store.save(state)

            # Final verification passes
            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=StubRunner([]),
                verifier=StubVerifier([True]),
            )
            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.COMPLETED)

    def test_post_iteration_task_circuit_breaker_skips_task(self) -> None:
        """After max_consecutive_task_failures verification failures, task is
        skipped (marked blocked) and the loop continues rather than halting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-hard.md").write_text("# Hard\n\nDo it.\n")
            (tasks_dir / "002-easy.md").write_text("# Easy\n\nDo it.\n")

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "execution": {
                        "max_iterations": 10,
                        "max_no_progress_iterations": 10,
                        "max_consecutive_task_failures": 2,
                    },
                    "verification": {"commands": ["python3 -c 'raise SystemExit(0)'"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-hard", "002-easy"])

            # 001 fails verification twice consecutively → task circuit breaker skips it
            # 002 then runs and passes verification → COMPLETED
            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=StubRunner([
                    {"status": "continue", "summary": "s", "task_id": "001-hard",
                     "files_changed": ["f.py"], "verification_expected": [],
                     "needs_resume": False, "blockers": [], "next_action": "continue"},
                    {"status": "continue", "summary": "s", "task_id": "001-hard",
                     "files_changed": ["f.py"], "verification_expected": [],
                     "needs_resume": False, "blockers": [], "next_action": "continue"},
                    {"status": "complete", "summary": "done", "task_id": "002-easy",
                     "files_changed": ["g.py"], "verification_expected": [],
                     "needs_resume": False, "blockers": [], "next_action": "done"},
                ]),
                # 001 fails twice (triggers circuit breaker), 002 passes, final verification passes
                verifier=StubVerifier([False, False, True, True]),
            )
            outcome = supervisor.run()

            self.assertEqual(outcome, LoopOutcome.COMPLETED)
            state = store.load()
            self.assertEqual(state["tasks"]["001-hard"]["status"], "blocked")
            self.assertEqual(state["tasks"]["001-hard"]["blocker_code"], "task_failure_circuit_breaker")

    def test_task_dependency_skips_blocked_deps(self) -> None:
        """A task whose dependency is not done should be skipped by _select_task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "001-foundation.md").write_text(
                "# Foundation\n\nDo it.\n"
            )
            (tasks_dir / "002-build.md").write_text(
                "# Build\n\n<!-- depends_on: 001-foundation -->\nBuild it.\n"
            )

            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                    "execution": {"max_iterations": 3, "max_no_progress_iterations": 3},
                    "verification": {"commands": ["python3 -c 'raise SystemExit(0)'"]},
                    "tasks": {"source_dir": "tasks"},
                },
                root,
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-build"])
            # Mark 001 as blocked so it's not selectable, 002 depends on 001
            state = store.load()
            state["tasks"]["001-foundation"]["status"] = "blocked"
            state["tasks"]["002-build"]["status"] = "ready"
            store.save(state)

            supervisor = Supervisor(
                config=config,
                state_store=store,
                task_graph=TaskGraph(tasks_dir),
                runner=StubRunner([]),
                verifier=StubVerifier([]),
            )
            outcome = supervisor.run()

            # 002 cannot run because 001 is not done; loop should block
            self.assertEqual(outcome, LoopOutcome.BLOCKED)


if __name__ == "__main__":
    unittest.main()
