from __future__ import annotations

from enum import Enum
from pathlib import Path
import time

from .config import CodexLoopConfig
from .hooks import HookRunner
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
        hook_runner: HookRunner | None = None,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.task_graph = task_graph
        self.runner = runner
        self.verifier = verifier
        self.working_directory = working_directory or config.project_dir
        self.hook_runner = hook_runner

    def run(self) -> LoopOutcome:
        for _ in range(self.config.execution.max_iterations):
            task = self._select_task()
            if task is None:
                return self._terminal_outcome_without_selectable_task()
            state = self.state_store.load()
            task_state = state["tasks"][task.task_id]
            self._run_hooks(
                event_name="pre_iteration",
                task=task,
                extra_env={
                    "CODEX_LOOP_TASK_STATUS": task_state.get("status"),
                    "CODEX_LOOP_LOOP_ITERATION": state["meta"].get("iteration", 0) + 1,
                },
            )
            try:
                result = self.runner.run_task(
                    task=task,
                    resume_session=task_state.get("session_id"),
                )
            except RuntimeError as exc:
                updated = self.state_store.record_runner_failure(
                    task_id=task.task_id,
                    reason=str(exc),
                    session_id=(
                        str(task_state["session_id"])
                        if task_state.get("session_id")
                        else None
                    ),
                )
                self._run_hooks(
                    event_name="post_iteration",
                    task=task,
                    extra_env={
                        "CODEX_LOOP_AGENT_STATUS": "runner_failure",
                        "CODEX_LOOP_VERIFICATION_PASSED": "false",
                        "CODEX_LOOP_ERROR": str(exc),
                    },
                )
                if (
                    self.config.execution.max_consecutive_runner_failures > 0
                    and updated["meta"]["consecutive_runner_failures"]
                    >= self.config.execution.max_consecutive_runner_failures
                ):
                    self.state_store.mark_blocked(
                        task.task_id,
                        "Reached runner failure circuit breaker.",
                    )
                    return LoopOutcome.BLOCKED
                if (
                    updated["meta"]["no_progress_iterations"]
                    >= self.config.execution.max_no_progress_iterations
                ):
                    self.state_store.mark_blocked(task.task_id, "Reached no-progress limit.")
                    return LoopOutcome.BLOCKED
                if self.config.execution.iteration_backoff_seconds > 0:
                    time.sleep(self.config.execution.iteration_backoff_seconds)
                continue
            passed, verification_results = self.verifier.run(
                self.config.verification.commands,
                self.working_directory,
                self.config.verification.pass_requires_all,
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
                resume_fallback_used=bool(result.get("resume_fallback_used", False)),
                resume_failure_reason=(
                    str(result["resume_failure_reason"])
                    if result.get("resume_failure_reason")
                    else None
                ),
            )
            self._run_hooks(
                event_name="post_iteration",
                task=task,
                extra_env={
                    "CODEX_LOOP_AGENT_STATUS": str(result.get("status", "continue")),
                    "CODEX_LOOP_VERIFICATION_PASSED": str(passed).lower(),
                    "CODEX_LOOP_SUMMARY": str(result.get("summary", "")),
                },
            )
            if str(result.get("status")) == "blocked":
                return LoopOutcome.BLOCKED
            if passed:
                updated = self.state_store.mark_task_done(task.task_id)
                if updated["meta"]["overall_status"] == "completed":
                    return LoopOutcome.COMPLETED
            if (
                self.config.execution.max_consecutive_verification_failures > 0
                and updated["meta"]["consecutive_verification_failures"]
                >= self.config.execution.max_consecutive_verification_failures
            ):
                self.state_store.mark_blocked(
                    task.task_id,
                    "Reached verification failure circuit breaker.",
                )
                return LoopOutcome.BLOCKED
            if (
                updated["meta"]["no_progress_iterations"]
                >= self.config.execution.max_no_progress_iterations
            ):
                self.state_store.mark_blocked(task.task_id, "Reached no-progress limit.")
                return LoopOutcome.BLOCKED
            if self.config.execution.iteration_backoff_seconds > 0:
                time.sleep(self.config.execution.iteration_backoff_seconds)
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

    def _terminal_outcome_without_selectable_task(self) -> LoopOutcome:
        state = self.state_store.load()
        tasks = state.get("tasks", {})
        if not tasks:
            return LoopOutcome.BLOCKED
        statuses = {task_state.get("status") for task_state in tasks.values()}
        if statuses == {"done"}:
            return LoopOutcome.COMPLETED
        first_incomplete = next(
            (
                task_id
                for task_id, task_state in tasks.items()
                if task_state.get("status") != "done"
            ),
            None,
        )
        if first_incomplete is not None:
            self.state_store.mark_blocked(
                first_incomplete,
                "No selectable task found while unfinished tasks remain.",
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

    def _run_hooks(
        self,
        *,
        event_name: str,
        task: Task,
        extra_env: dict[str, object] | None = None,
    ) -> None:
        if self.hook_runner is None:
            return
        commands = getattr(self.config.hooks, event_name, [])
        if not commands:
            return
        env = {
            "CODEX_LOOP_PROJECT_DIR": str(self.config.project_dir),
            "CODEX_LOOP_WORKING_DIR": str(self.working_directory),
            "CODEX_LOOP_TASK_ID": task.task_id,
            "CODEX_LOOP_TASK_TITLE": task.title,
        }
        env.update(extra_env or {})
        self.hook_runner.run(
            event_name=event_name,
            commands=commands,
            cwd=self.working_directory,
            env=env,
            timeout_seconds=self.config.hooks.timeout_seconds,
        )
