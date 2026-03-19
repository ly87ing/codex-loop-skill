from __future__ import annotations

from enum import Enum
from pathlib import Path

from .config import CodexLoopConfig
from .state_store import StateStore
from .task_graph import Task, TaskGraph


class LoopOutcome(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"


class Supervisor:
    def __init__(
        self,
        *,
        config: CodexLoopConfig,
        state_store: StateStore,
        task_graph: TaskGraph,
        runner: object,
        verifier: object,
        working_directory: Path | None = None,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.task_graph = task_graph
        self.runner = runner
        self.verifier = verifier
        self.working_directory = working_directory or config.project_dir

    def run(self) -> LoopOutcome:
        for _ in range(self.config.execution.max_iterations):
            task = self._select_task()
            if task is None:
                return LoopOutcome.COMPLETED
            state = self.state_store.load()
            task_state = state["tasks"][task.task_id]
            result = self.runner.run_task(
                task=task,
                resume_session=task_state.get("session_id"),
            )
            passed, verification_results = self.verifier.run(
                self.config.verification.commands,
                self.working_directory,
            )
            files_changed = [
                str(path)
                for path in result.get("files_changed", [])
                if isinstance(path, str)
            ]
            fingerprint = self._fingerprint(task.task_id, files_changed, passed, result)
            updated = self.state_store.record_iteration(
                task_id=task.task_id,
                summary=str(result.get("summary", "")),
                fingerprint=fingerprint,
                files_changed=files_changed,
                verification_passed=passed,
                agent_status=str(result.get("status", "continue")),
                session_id=(
                    str(result["session_id"]) if result.get("session_id") else None
                ),
                verification_results=verification_results,
                blockers=[
                    str(item)
                    for item in result.get("blockers", [])
                    if isinstance(item, str)
                ],
            )
            if str(result.get("status")) == "blocked":
                return LoopOutcome.BLOCKED
            if passed:
                updated = self.state_store.mark_task_done(task.task_id)
                if updated["meta"]["overall_status"] == "completed":
                    return LoopOutcome.COMPLETED
            if (
                updated["meta"]["no_progress_iterations"]
                >= self.config.execution.max_no_progress_iterations
            ):
                self.state_store.mark_blocked(task.task_id, "Reached no-progress limit.")
                return LoopOutcome.BLOCKED
        state = self.state_store.load()
        remaining = [
            task_id
            for task_id, task_state in state["tasks"].items()
            if task_state["status"] != "done"
        ]
        if remaining:
            self.state_store.mark_blocked(
                remaining[0],
                "Reached max iterations before completion.",
            )
        return LoopOutcome.BLOCKED

    def _select_task(self) -> Task | None:
        tasks = self.task_graph.discover()
        state = self.state_store.load()
        for task in tasks:
            status = state["tasks"].get(task.task_id, {}).get("status")
            if status in {"ready", "in_progress"}:
                return task
        return None

    @staticmethod
    def _fingerprint(
        task_id: str,
        files_changed: list[str],
        passed: bool,
        result: dict[str, object],
    ) -> str:
        joined = ",".join(files_changed)
        return f"{task_id}|{joined}|{passed}|{result.get('status', 'continue')}"

