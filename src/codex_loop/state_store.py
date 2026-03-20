from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from .metrics import write_metrics_snapshot
from pathlib import Path
from typing import Any


def _default_task_status(index: int) -> str:
    return "ready" if index == 0 else "pending"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_task_state(index: int) -> dict[str, Any]:
    return {
        "status": _default_task_status(index),
        "session_id": None,
        "iterations": 0,
        "consecutive_task_failures": 0,
        "last_summary": "",
        "files_changed": [],
        "last_error": None,
        "blocker_code": None,
        "blocker_reason": None,
        "resume_fallback_used": False,
        "resume_failure_reason": None,
        "updated_at": _now(),
    }


def _normalize_task_statuses(tasks: dict[str, dict[str, Any]]) -> None:
    active_seen = False
    for task in tasks.values():
        status = task.get("status")
        if status in {"done", "blocked"}:
            continue
        if not active_seen and status in {"ready", "in_progress"}:
            active_seen = True
            continue
        task["status"] = "pending"
    if active_seen:
        return
    for task in tasks.values():
        if task.get("status") not in {"done", "blocked"}:
            task["status"] = "ready"
            break


@dataclass(slots=True)
class StateStore:
    path: Path

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)
        try:
            write_metrics_snapshot(self.path.parent / "metrics.json", state)
        except OSError:
            pass

    def create_initial(
        self,
        project_name: str,
        source_prompt: str,
        tasks: list[str],
    ) -> dict[str, Any]:
        state = {
            "meta": {
                "project_name": project_name,
                "source_prompt": source_prompt,
                "iteration": 0,
                "no_progress_iterations": 0,
                "consecutive_runner_failures": 0,
                "consecutive_verification_failures": 0,
                "last_fingerprint": "",
                "last_error": None,
                "last_blocker": None,
                "overall_status": "initialized",
                "archived_tasks": {},
                "created_at": _now(),
                "updated_at": _now(),
            },
            "tasks": {
                task_id: _default_task_state(index)
                for index, task_id in enumerate(tasks)
            },
            "history": [],
        }
        self.save(state)
        return state

    def ensure_initialized(
        self,
        *,
        project_name: str,
        source_prompt: str,
    ) -> dict[str, Any]:
        if self.path.exists():
            return self.load()
        return self.create_initial(
            project_name=project_name,
            source_prompt=source_prompt,
            tasks=[],
        )

    def reconcile_tasks(self, task_ids: list[str]) -> dict[str, Any]:
        state = self.load()
        meta = state["meta"]
        meta.setdefault("archived_tasks", {})
        meta.setdefault("consecutive_runner_failures", 0)
        meta.setdefault("consecutive_verification_failures", 0)
        meta.setdefault("last_error", None)
        meta.setdefault("last_blocker", None)
        current_tasks = state.get("tasks", {})
        removed_task_ids = [task_id for task_id in current_tasks if task_id not in task_ids]
        for task_id in removed_task_ids:
            meta["archived_tasks"][task_id] = current_tasks.pop(task_id)

        rebuilt_tasks: dict[str, dict[str, Any]] = {}
        for index, task_id in enumerate(task_ids):
            task_state = current_tasks.get(task_id)
            if task_state is None:
                task_state = _default_task_state(index)
            task_state.setdefault("resume_fallback_used", False)
            task_state.setdefault("resume_failure_reason", None)
            task_state.setdefault("last_error", None)
            task_state.setdefault("blocker_code", None)
            task_state.setdefault("blocker_reason", None)
            task_state.setdefault("consecutive_task_failures", 0)
            task_state.setdefault("last_verification_results", [])
            rebuilt_tasks[task_id] = task_state

        _normalize_task_statuses(rebuilt_tasks)
        state["tasks"] = rebuilt_tasks
        if rebuilt_tasks and all(
            task["status"] == "done" for task in rebuilt_tasks.values()
        ):
            meta["overall_status"] = "completed"
        elif any(task["status"] == "blocked" for task in rebuilt_tasks.values()):
            meta["overall_status"] = "blocked"
        elif rebuilt_tasks:
            meta["overall_status"] = "running"
        else:
            meta["overall_status"] = "initialized"
        meta["updated_at"] = _now()
        self.save(state)
        return state

    def mark_task_done(self, task_id: str) -> dict[str, Any]:
        state = self.load()
        state["tasks"][task_id]["status"] = "done"
        state["tasks"][task_id]["last_error"] = None
        state["tasks"][task_id]["blocker_code"] = None
        state["tasks"][task_id]["blocker_reason"] = None
        state["tasks"][task_id]["updated_at"] = _now()
        next_pending = next(
            (key for key, task in state["tasks"].items() if task["status"] == "pending"),
            None,
        )
        if next_pending is not None:
            state["tasks"][next_pending]["status"] = "ready"
            state["tasks"][next_pending]["updated_at"] = _now()
        elif all(task["status"] == "done" for task in state["tasks"].values()):
            state["meta"]["overall_status"] = "completed"
        state["meta"]["updated_at"] = _now()
        self.save(state)
        return state

    def mark_blocked(
        self,
        task_id: str,
        reason: str,
        code: str = "blocked",
    ) -> dict[str, Any]:
        state = self.load()
        state["tasks"][task_id]["status"] = "blocked"
        state["tasks"][task_id]["blocker_code"] = code
        state["tasks"][task_id]["blocker_reason"] = reason
        state["tasks"][task_id]["last_error"] = reason
        state["tasks"][task_id]["updated_at"] = _now()
        # When a task is skipped by the task-level circuit breaker, promote
        # the next pending task to ready so the loop can continue.
        if code == "task_failure_circuit_breaker":
            next_pending = next(
                (key for key, task in state["tasks"].items() if task["status"] == "pending"),
                None,
            )
            if next_pending is not None:
                state["tasks"][next_pending]["status"] = "ready"
                state["tasks"][next_pending]["updated_at"] = _now()
        state["meta"]["last_error"] = reason
        state["meta"]["last_blocker"] = {
            "task_id": task_id,
            "code": code,
            "reason": reason,
            "timestamp": _now(),
        }
        # task_failure_circuit_breaker skips one task but the loop continues;
        # do not mark the overall run as blocked. Also reset the global
        # verification failure counter so the next task starts with a clean slate.
        if code != "task_failure_circuit_breaker":
            state["meta"]["overall_status"] = "blocked"
        else:
            state["meta"]["consecutive_verification_failures"] = 0
            state["meta"]["consecutive_runner_failures"] = 0
        state["meta"]["updated_at"] = _now()
        state["history"].append(
            {
                "event_type": "blocked",
                "timestamp": _now(),
                "iteration": state["meta"].get("iteration", 0),
                "task_id": task_id,
                "summary": reason,
                "blocker_code": code,
                "blocker_reason": reason,
            }
        )
        self.save(state)
        return state

    def requeue_blocked_tasks(self, task_id: str | None = None) -> dict[str, Any]:
        state = self.load()
        tasks = state.get("tasks", {})
        target_ids = [
            current_task_id
            for current_task_id, task_state in tasks.items()
            if task_state.get("status") == "blocked"
            and (task_id is None or current_task_id == task_id)
        ]
        if not target_ids:
            return state

        timestamp = _now()
        for current_task_id in target_ids:
            task_state = tasks[current_task_id]
            previous_code = task_state.get("blocker_code")
            previous_reason = task_state.get("blocker_reason")
            task_state["status"] = "pending"
            task_state["blocker_code"] = None
            task_state["blocker_reason"] = None
            task_state["last_error"] = None
            task_state["consecutive_task_failures"] = 0
            task_state["updated_at"] = timestamp
            state["history"].append(
                {
                    "event_type": "requeued",
                    "timestamp": timestamp,
                    "iteration": state["meta"].get("iteration", 0),
                    "task_id": current_task_id,
                    "summary": "Requeued blocked task for retry.",
                    "blocker_code": previous_code,
                    "blocker_reason": previous_reason,
                }
            )

        _normalize_task_statuses(tasks)
        state["meta"]["no_progress_iterations"] = 0
        state["meta"]["consecutive_runner_failures"] = 0
        state["meta"]["consecutive_verification_failures"] = 0
        state["meta"]["last_error"] = None
        state["meta"]["last_blocker"] = None
        state["meta"]["overall_status"] = (
            "completed"
            if tasks and all(task.get("status") == "done" for task in tasks.values())
            else "running"
        )
        state["meta"]["updated_at"] = timestamp
        self.save(state)
        return state

    def record_runner_failure(
        self,
        *,
        task_id: str,
        reason: str,
        session_id: str | None = None,
        transient: bool = False,
    ) -> dict[str, Any]:
        state = self.load()
        meta = state["meta"]
        task = state["tasks"][task_id]
        meta["iteration"] += 1
        meta["updated_at"] = _now()
        # Transient failures (network, timeout, kill signal) are infrastructure
        # blips, not real loop stalls — do not penalise the no-progress counter.
        if not transient:
            meta["no_progress_iterations"] += 1
        # Transient failures do not count toward the structural runner-failure
        # circuit breaker either.
        if not transient:
            meta["consecutive_runner_failures"] = int(
                meta.get("consecutive_runner_failures", 0)
            ) + 1
        meta["consecutive_verification_failures"] = 0
        meta["last_error"] = reason
        meta["overall_status"] = "running"
        task["iterations"] += 1
        if not transient:
            task["consecutive_task_failures"] = int(task.get("consecutive_task_failures", 0)) + 1
        task["status"] = "in_progress"
        task["last_summary"] = reason
        task["last_error"] = reason
        task["blocker_code"] = None
        task["blocker_reason"] = None
        task["files_changed"] = []
        if session_id is not None:
            task["session_id"] = session_id
        task["updated_at"] = _now()
        state["history"].append(
            {
                "event_type": "runner_failure",
                "timestamp": _now(),
                "iteration": meta["iteration"],
                "task_id": task_id,
                "summary": reason,
                "fingerprint": f"{task_id}|runner_failure|{meta['iteration']}",
                "files_changed": [],
                "verification_passed": False,
                "agent_status": "runner_failure",
                "session_id": task.get("session_id"),
                "verification_results": [],
                "blockers": [],
                "resume_fallback_used": False,
                "resume_failure_reason": None,
                "error": reason,
            }
        )
        self.save(state)
        return state

    def record_iteration(
        self,
        *,
        task_id: str,
        summary: str,
        fingerprint: str,
        files_changed: list[str],
        verification_passed: bool,
        agent_status: str,
        session_id: str | None = None,
        verification_results: list[dict[str, Any]] | None = None,
        blockers: list[str] | None = None,
        resume_fallback_used: bool = False,
        resume_failure_reason: str | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        meta = state["meta"]
        task = state["tasks"][task_id]
        meta["iteration"] += 1
        meta["updated_at"] = _now()
        task["iterations"] += 1
        if not files_changed and not verification_passed:
            meta["no_progress_iterations"] += 1
        else:
            meta["no_progress_iterations"] = 0
        meta["consecutive_runner_failures"] = 0
        if verification_passed:
            meta["consecutive_verification_failures"] = 0
        else:
            meta["consecutive_verification_failures"] = int(
                meta.get("consecutive_verification_failures", 0)
            ) + 1
        meta["last_error"] = None if verification_passed else summary
        meta["last_fingerprint"] = fingerprint
        task["last_summary"] = summary
        task["files_changed"] = files_changed
        if session_id is not None:
            task["session_id"] = session_id
        task["last_error"] = None if verification_passed else summary
        task["last_verification_results"] = verification_results or []
        task["blocker_code"] = None
        task["blocker_reason"] = None
        task["resume_fallback_used"] = resume_fallback_used
        task["resume_failure_reason"] = resume_failure_reason
        task["updated_at"] = _now()
        if verification_passed:
            task["consecutive_task_failures"] = 0
        else:
            task["consecutive_task_failures"] = int(task.get("consecutive_task_failures", 0)) + 1
        if agent_status == "blocked":
            task["status"] = "blocked"
            meta["overall_status"] = "blocked"
        elif verification_passed:
            task["status"] = "done"
        else:
            task["status"] = "in_progress"
            meta["overall_status"] = "running"
        state["history"].append(
            {
                "event_type": "iteration",
                "timestamp": _now(),
                "iteration": meta["iteration"],
                "task_id": task_id,
                "summary": summary,
                "fingerprint": fingerprint,
                "files_changed": files_changed,
                "verification_passed": verification_passed,
                "agent_status": agent_status,
                "session_id": session_id,
                "verification_results": verification_results or [],
                "blockers": blockers or [],
                "resume_fallback_used": resume_fallback_used,
                "resume_failure_reason": resume_failure_reason,
            }
        )
        self.save(state)
        return state

    def record_watchdog_event(
        self,
        *,
        event_type: str,
        summary: str,
        restart_reason: str,
        restart_count: int,
        child_pid: int | None,
        child_exit_code: int | None = None,
        watchdog_phase: str | None = None,
    ) -> dict[str, Any]:
        state = self.ensure_initialized(
            project_name=self.path.parent.parent.name,
            source_prompt="Watchdog runtime state",
        )
        history = state.setdefault("history", [])
        history.append(
            {
                "event_type": event_type,
                "timestamp": _now(),
                "iteration": state.get("meta", {}).get("iteration", 0),
                "task_id": None,
                "summary": summary,
                "restart_reason": restart_reason,
                "restart_count": restart_count,
                "child_pid": child_pid,
                "child_exit_code": child_exit_code,
                "watchdog_phase": watchdog_phase,
            }
        )
        state["meta"]["updated_at"] = _now()
        self.save(state)
        return state
