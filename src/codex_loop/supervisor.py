from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
import random
import subprocess
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
        sleep_fn: object | None = None,
        jitter_fn: object | None = None,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.task_graph = task_graph
        self.runner = runner
        self.verifier = verifier
        self.working_directory = working_directory or config.project_dir
        self.hook_runner = hook_runner
        self.sleep_fn = sleep_fn or time.sleep
        self.jitter_fn = jitter_fn or random.uniform

    def run(self) -> LoopOutcome:
        for _ in range(self.config.execution.max_iterations):
            task = self._select_task()
            if task is None:
                outcome = self._terminal_outcome_without_selectable_task()
                if outcome is None:
                    # Final verification failed after all tasks done; a task
                    # was reopened — continue the loop to fix it.
                    self._sleep_between_iterations()
                    continue
                state = self.state_store.load()
                last_blocker = state.get("meta", {}).get("last_blocker") or {}
                extra_env = None
                if outcome == LoopOutcome.BLOCKED and last_blocker:
                    extra_env = {
                        "CODEX_LOOP_ERROR": last_blocker.get("reason"),
                        "CODEX_LOOP_BLOCKER_CODE": last_blocker.get("code"),
                    }
                self._run_terminal_hooks(outcome=outcome, task=None, extra_env=extra_env)
                if outcome == LoopOutcome.COMPLETED:
                    print("All tasks done and verification passed.", flush=True)
                return outcome
            state = self.state_store.load()
            iteration_num = state["meta"].get("iteration", 0) + 1
            _all_tasks = state.get("tasks", {})
            _done_count = sum(1 for t in _all_tasks.values() if t.get("status") == "done")
            _total_count = len(_all_tasks)
            _ts = datetime.now(UTC).strftime("%H:%M:%S")
            print(f"[iteration {iteration_num}] task: {task.task_id}  ({_done_count}/{_total_count} done, running Codex...) [{_ts}]", flush=True)
            task_state = state["tasks"][task.task_id]
            hook_failure = self._run_hooks(
                event_name="pre_iteration",
                task=task,
                extra_env={
                    "CODEX_LOOP_TASK_STATUS": task_state.get("status"),
                    "CODEX_LOOP_LOOP_ITERATION": state["meta"].get("iteration", 0) + 1,
                },
            )
            if hook_failure is not None:
                self.state_store.mark_blocked(
                    task.task_id,
                    hook_failure,
                    code="hook_failure",
                )
                self._run_terminal_hooks(
                    outcome=LoopOutcome.BLOCKED,
                    task=task,
                    extra_env={
                        "CODEX_LOOP_ERROR": hook_failure,
                        "CODEX_LOOP_BLOCKER_CODE": "hook_failure",
                    },
                )
                return LoopOutcome.BLOCKED
            try:
                result = self.runner.run_task(
                    task=task,
                    resume_session=task_state.get("session_id"),
                )
            except (RuntimeError, FileNotFoundError, OSError, ValueError) as exc:
                is_transient = self._is_transient_runner_error(str(exc))
                _err_kind = "retrying" if self._is_transient_runner_error(str(exc)) else "will stop if repeated"
                print(f"  -> runner error ({_err_kind}): {str(exc)[:120]}", flush=True)
                updated = self.state_store.record_runner_failure(
                    task_id=task.task_id,
                    reason=str(exc),
                    session_id=(
                        str(task_state["session_id"])
                        if task_state.get("session_id")
                        else None
                    ),
                    transient=is_transient,
                )
                hook_failure = self._run_hooks(
                    event_name="post_iteration",
                    task=task,
                    extra_env={
                        "CODEX_LOOP_AGENT_STATUS": "runner_failure",
                        "CODEX_LOOP_VERIFICATION_PASSED": "false",
                        "CODEX_LOOP_ERROR": str(exc),
                    },
                )
                if hook_failure is not None:
                    self.state_store.mark_blocked(
                        task.task_id,
                        hook_failure,
                        code="hook_failure",
                    )
                    self._run_terminal_hooks(
                        outcome=LoopOutcome.BLOCKED,
                        task=task,
                        extra_env={
                            "CODEX_LOOP_ERROR": hook_failure,
                            "CODEX_LOOP_BLOCKER_CODE": "hook_failure",
                        },
                    )
                    return LoopOutcome.BLOCKED
                # Transient errors get a backoff-and-retry without touching
                # the structural circuit breakers.
                if is_transient:
                    self._sleep_between_iterations()
                    continue
                if (
                    self.config.execution.max_consecutive_runner_failures > 0
                    and updated["meta"]["consecutive_runner_failures"]
                    >= self.config.execution.max_consecutive_runner_failures
                ):
                    self.state_store.mark_blocked(
                        task.task_id,
                        "Reached runner failure circuit breaker.",
                        code="runner_failure_circuit_breaker",
                    )
                    self._run_terminal_hooks(
                        outcome=LoopOutcome.BLOCKED,
                        task=task,
                        extra_env={
                            "CODEX_LOOP_ERROR": "Reached runner failure circuit breaker.",
                            "CODEX_LOOP_BLOCKER_CODE": "runner_failure_circuit_breaker",
                        },
                    )
                    return LoopOutcome.BLOCKED
                # Task-level circuit breaker: skip this task instead of
                # blocking the entire loop.
                task_failures = updated["tasks"][task.task_id].get(
                    "consecutive_task_failures", 0
                )
                max_task_failures = self.config.execution.max_consecutive_task_failures
                if max_task_failures > 0 and task_failures >= max_task_failures:
                    self.state_store.mark_blocked(
                        task.task_id,
                        f"Task failed {task_failures} times consecutively.",
                        code="task_failure_circuit_breaker",
                    )
                    self._sleep_between_iterations()
                    continue
                if (
                    updated["meta"]["no_progress_iterations"]
                    >= self.config.execution.max_no_progress_iterations
                ):
                    self.state_store.mark_blocked(
                        task.task_id,
                        "Reached no-progress limit.",
                        code="no_progress_limit",
                    )
                    self._run_terminal_hooks(
                        outcome=LoopOutcome.BLOCKED,
                        task=task,
                        extra_env={
                            "CODEX_LOOP_ERROR": "Reached no-progress limit.",
                            "CODEX_LOOP_BLOCKER_CODE": "no_progress_limit",
                        },
                    )
                    return LoopOutcome.BLOCKED
                self._sleep_between_iterations()
                continue
            if not self.config.verification.commands:
                passed, verification_results = True, []
            else:
                passed, verification_results = self.verifier.run(
                    self.config.verification.commands,
                    self.working_directory,
                    self.config.verification.pass_requires_all,
                    self.config.verification.timeout_seconds,
                )
            files_changed = self._real_files_changed(
                self.working_directory,
                result.get("files_changed", []),
            )
            _status = str(result.get("status", "continue"))
            _verify = "verification=pass" if passed else "verification=FAIL"
            _files = f"files_changed={len(files_changed)}"
            print(f"  -> status={_status} {_verify} {_files}", flush=True)
            if not passed and verification_results:
                first_fail = next((r for r in verification_results if r.get("exit_code") != 0 or r.get("timed_out")), None)
                if first_fail:
                    _stderr = str(first_fail.get("stderr", "")).strip()
                    _stdout = str(first_fail.get("stdout", "")).strip()
                    _snippet = (_stderr or _stdout)[:200].strip()
                    if _snippet:
                        print(f"     verification error: {_snippet}", flush=True)
            fingerprint = self._fingerprint(task.task_id, files_changed, passed, result)
            if not files_changed and not passed:
                _no_prog = state["meta"].get("no_progress_iterations", 0) + 1
                _max_no_prog = self.config.execution.max_no_progress_iterations
                print(
                    f"     (no file changes detected; "
                    f"{_no_prog}/{_max_no_prog} no-progress iterations)",
                    flush=True,
                )
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
            hook_failure = self._run_hooks(
                event_name="post_iteration",
                task=task,
                extra_env={
                    "CODEX_LOOP_AGENT_STATUS": str(result.get("status", "continue")),
                    "CODEX_LOOP_VERIFICATION_PASSED": str(passed).lower(),
                    "CODEX_LOOP_SUMMARY": str(result.get("summary", "")),
                },
            )
            if hook_failure is not None:
                self.state_store.mark_blocked(
                    task.task_id,
                    hook_failure,
                    code="hook_failure",
                )
                self._run_terminal_hooks(
                    outcome=LoopOutcome.BLOCKED,
                    task=task,
                    extra_env={
                        "CODEX_LOOP_ERROR": hook_failure,
                        "CODEX_LOOP_BLOCKER_CODE": "hook_failure",
                    },
                )
                return LoopOutcome.BLOCKED
            if str(result.get("status")) == "blocked":
                blocker_reason = next(
                    (
                        str(item)
                        for item in result.get("blockers", [])
                        if isinstance(item, str)
                    ),
                    "Agent returned blocked.",
                )
                self.state_store.mark_blocked(
                    task.task_id,
                    blocker_reason,
                    code="agent_blocked",
                )
                self._run_terminal_hooks(
                    outcome=LoopOutcome.BLOCKED,
                    task=task,
                    extra_env={
                        "CODEX_LOOP_ERROR": blocker_reason,
                        "CODEX_LOOP_BLOCKER_CODE": "agent_blocked",
                    },
                )
                return LoopOutcome.BLOCKED
            if passed:
                self.state_store.mark_task_done(task.task_id)
                # Do NOT short-circuit to COMPLETED here — always let
                # _terminal_outcome_without_selectable_task run the final
                # verification pass before declaring COMPLETED. This prevents
                # a task reporting done from bypassing the verification gate.
                continue
            if (
                self.config.execution.max_consecutive_verification_failures > 0
                and updated["meta"]["consecutive_verification_failures"]
                >= self.config.execution.max_consecutive_verification_failures
            ):
                self.state_store.mark_blocked(
                    task.task_id,
                    "Reached verification failure circuit breaker.",
                    code="verification_failure_circuit_breaker",
                )
                self._run_terminal_hooks(
                    outcome=LoopOutcome.BLOCKED,
                    task=task,
                    extra_env={
                        "CODEX_LOOP_ERROR": "Reached verification failure circuit breaker.",
                        "CODEX_LOOP_BLOCKER_CODE": "verification_failure_circuit_breaker",
                    },
                )
                return LoopOutcome.BLOCKED
            # Task-level circuit breaker after verification failure.
            # Skip this task instead of blocking the entire loop.
            task_failures = updated["tasks"][task.task_id].get(
                "consecutive_task_failures", 0
            )
            max_task_failures = self.config.execution.max_consecutive_task_failures
            if max_task_failures > 0 and task_failures >= max_task_failures:
                self.state_store.mark_blocked(
                    task.task_id,
                    f"Task failed {task_failures} times consecutively.",
                    code="task_failure_circuit_breaker",
                )
                self._sleep_between_iterations()
                continue
            if (
                updated["meta"]["no_progress_iterations"]
                >= self.config.execution.max_no_progress_iterations
            ):
                self.state_store.mark_blocked(
                    task.task_id,
                    "Reached no-progress limit.",
                    code="no_progress_limit",
                )
                self._run_terminal_hooks(
                    outcome=LoopOutcome.BLOCKED,
                    task=task,
                    extra_env={
                        "CODEX_LOOP_ERROR": "Reached no-progress limit.",
                        "CODEX_LOOP_BLOCKER_CODE": "no_progress_limit",
                    },
                )
                return LoopOutcome.BLOCKED
            self._sleep_between_iterations()
        state = self.state_store.load()
        remaining = [
            task_id
            for task_id, task_state in state["tasks"].items()
            if task_state["status"] not in {"done", "blocked"}
        ]
        if remaining:
            self.state_store.mark_blocked(
                remaining[0],
                "Reached max iterations before completion.",
                code="max_iterations",
            )
        terminal_task = self._select_task()
        self._run_terminal_hooks(
            outcome=LoopOutcome.BLOCKED,
            task=terminal_task,
            extra_env={
                "CODEX_LOOP_ERROR": "Reached max iterations before completion.",
                "CODEX_LOOP_BLOCKER_CODE": "max_iterations",
            },
        )
        return LoopOutcome.BLOCKED

    def _terminal_outcome_without_selectable_task(self) -> LoopOutcome | None:
        state = self.state_store.load()
        tasks = state.get("tasks", {})
        if not tasks:
            return LoopOutcome.BLOCKED
        statuses = {task_state.get("status") for task_state in tasks.values()}
        # Consider the loop complete when every task is either done or was
        # intentionally skipped by the task-level circuit breaker (blocked).
        # Pure done, or done+blocked (some tasks skipped) — both warrant a
        # final verification pass before declaring COMPLETED.
        if statuses <= {"done", "blocked"} and "done" in statuses:
            # Skip final verification when no commands are configured — treat
            # as passed so the loop can declare COMPLETED instead of blocking.
            if not self.config.verification.commands:
                passed = True
            else:
                passed, _ = self.verifier.run(
                    self.config.verification.commands,
                    self.working_directory,
                    self.config.verification.pass_requires_all,
                    self.config.verification.timeout_seconds,
                )
            if passed:
                state["meta"]["overall_status"] = "completed"
                state["meta"]["updated_at"] = datetime.now(UTC).isoformat()
                self.state_store.save(state)
                return LoopOutcome.COMPLETED
            # Verification failed. Reopen the last done task so the loop can
            # continue fixing it (skipped/blocked tasks stay blocked).
            last_done_id = next(
                (
                    tid
                    for tid in reversed(list(tasks))
                    if tasks[tid].get("status") == "done"
                ),
                None,
            )
            if last_done_id is not None:
                task_obj = state["tasks"][last_done_id]
                task_obj["status"] = "ready"
                task_obj["last_error"] = "Final verification failed after all tasks reported done."
                task_obj["consecutive_task_failures"] = 0
                state["meta"]["overall_status"] = "running"
                self.state_store.save(state)
                print(
                    f"  (all tasks done but final verification failed — "
                    f"reopening {last_done_id} to fix it)",
                    flush=True,
                )
                return None  # caller handles None → continue loop
            # No done task to reopen — fall through to BLOCKED
        first_incomplete = next(
            (
                task_id
                for task_id, task_state in tasks.items()
                if task_state.get("status") not in {"done", "blocked"}
            ),
            None,
        )
        if first_incomplete is not None:
            self.state_store.mark_blocked(
                first_incomplete,
                "No selectable task found while unfinished tasks remain.",
                code="no_selectable_task",
            )
        return LoopOutcome.BLOCKED

    def _select_task(self) -> Task | None:
        tasks = self.task_graph.discover()
        state = self.state_store.load()
        task_states = state.get("tasks", {})
        done_ids = {
            tid
            for tid, ts in task_states.items()
            if ts.get("status") == "done"
        }
        # Tasks skipped by the task-level circuit breaker are blocked with this
        # specific code. Treat them as satisfied dependencies so downstream
        # tasks are not permanently deadlocked waiting for a skipped task.
        skipped_ids = {
            tid
            for tid, ts in task_states.items()
            if ts.get("status") == "blocked"
            and ts.get("blocker_code") == "task_failure_circuit_breaker"
        }
        satisfied_ids = done_ids | skipped_ids
        for task in tasks:
            status = task_states.get(task.task_id, {}).get("status")
            if status not in {"ready", "in_progress"}:
                continue
            # Skip tasks whose dependencies are not yet done or skipped.
            if any(dep not in satisfied_ids for dep in task.depends_on):
                continue
            return task
        return None

    @staticmethod
    def _is_transient_runner_error(message: str) -> bool:
        """Return True for errors that are temporary infrastructure failures.
        Transient errors should not consume the consecutive_runner_failures counter.
        """
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "timed out",
                "timeout",
                "connection reset",
                "connection refused",
                "broken pipe",
                "network",
                "killed",
                "sigkill",
                "sigterm",
                "rate limit",
                "429",
                "500",
                "502",
                "503",
                "overloaded",
                "temporarily unavailable",
            )
        )

    @staticmethod
    def _real_files_changed(
        working_directory: Path,
        agent_reported: list[object],
    ) -> list[str]:
        """Return files actually changed according to git, falling back to
        the agent-reported list only when git is unavailable."""
        for git_args in (
            ["git", "diff", "--name-only", "HEAD"],
            ["git", "diff", "--name-only", "--cached", "HEAD"],
        ):
            try:
                result = subprocess.run(
                    git_args,
                    cwd=working_directory,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip().splitlines()
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue
        return [str(p) for p in agent_reported if isinstance(p, str)]

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
    ) -> str | None:
        if self.hook_runner is None:
            return None
        commands = getattr(self.config.hooks, event_name, [])
        if not commands:
            return None
        env = {
            "CODEX_LOOP_PROJECT_DIR": str(self.config.project_dir),
            "CODEX_LOOP_WORKING_DIR": str(self.working_directory),
            "CODEX_LOOP_TASK_ID": task.task_id,
            "CODEX_LOOP_TASK_TITLE": task.title,
        }
        env.update(extra_env or {})
        results = self.hook_runner.run(
            event_name=event_name,
            commands=commands,
            cwd=self.working_directory,
            env=env,
            timeout_seconds=self.config.hooks.timeout_seconds,
        )
        if self.config.hooks.failure_policy != "block":
            return None
        failure = self.hook_runner.first_failure(results)
        return self.hook_runner.failure_reason(event_name, failure)

    def _run_terminal_hooks(
        self,
        *,
        outcome: LoopOutcome,
        task: Task | None,
        extra_env: dict[str, object] | None = None,
    ) -> None:
        if self.hook_runner is None:
            return
        event_name = "on_completed" if outcome == LoopOutcome.COMPLETED else "on_blocked"
        commands = getattr(self.config.hooks, event_name, [])
        if not commands:
            return
        env: dict[str, object] = {
            "CODEX_LOOP_PROJECT_DIR": str(self.config.project_dir),
            "CODEX_LOOP_WORKING_DIR": str(self.working_directory),
            "CODEX_LOOP_OUTCOME": outcome.value,
        }
        if task is not None:
            env["CODEX_LOOP_TASK_ID"] = task.task_id
            env["CODEX_LOOP_TASK_TITLE"] = task.title
        env.update(extra_env or {})
        self.hook_runner.run(
            event_name=event_name,
            commands=commands,
            cwd=self.working_directory,
            env=env,
            timeout_seconds=self.config.hooks.timeout_seconds,
        )

    def _sleep_between_iterations(self) -> None:
        base = float(self.config.execution.iteration_backoff_seconds)
        jitter = float(self.config.execution.iteration_backoff_jitter_seconds)
        if base <= 0 and jitter <= 0:
            return
        delay = max(base, 0.0)
        if jitter > 0:
            delay += float(self.jitter_fn(0.0, jitter))
        if delay > 0:
            self.sleep_fn(delay)
