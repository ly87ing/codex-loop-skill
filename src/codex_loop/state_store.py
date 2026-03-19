from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
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
        "last_summary": "",
        "files_changed": [],
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
                "last_fingerprint": "",
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

    def reconcile_tasks(self, task_ids: list[str]) -> dict[str, Any]:
        state = self.load()
        meta = state["meta"]
        meta.setdefault("archived_tasks", {})
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

    def mark_blocked(self, task_id: str, reason: str) -> dict[str, Any]:
        state = self.load()
        state["tasks"][task_id]["status"] = "blocked"
        state["tasks"][task_id]["blocker_reason"] = reason
        state["tasks"][task_id]["updated_at"] = _now()
        state["meta"]["overall_status"] = "blocked"
        state["meta"]["updated_at"] = _now()
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
        meta["last_fingerprint"] = fingerprint
        task["last_summary"] = summary
        task["files_changed"] = files_changed
        task["session_id"] = session_id
        task["resume_fallback_used"] = resume_fallback_used
        task["resume_failure_reason"] = resume_failure_reason
        task["updated_at"] = _now()
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
