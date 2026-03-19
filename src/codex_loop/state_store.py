from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


def _default_task_status(index: int) -> str:
    return "ready" if index == 0 else "pending"


@dataclass(slots=True)
class StateStore:
    path: Path

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

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
            },
            "tasks": {
                task_id: {
                    "status": _default_task_status(index),
                    "session_id": None,
                    "iterations": 0,
                    "last_summary": "",
                    "files_changed": [],
                }
                for index, task_id in enumerate(tasks)
            },
            "history": [],
        }
        self.save(state)
        return state

    def mark_task_done(self, task_id: str) -> dict[str, Any]:
        state = self.load()
        state["tasks"][task_id]["status"] = "done"
        next_pending = next(
            (key for key, task in state["tasks"].items() if task["status"] == "pending"),
            None,
        )
        if next_pending is not None:
            state["tasks"][next_pending]["status"] = "ready"
        elif all(task["status"] == "done" for task in state["tasks"].values()):
            state["meta"]["overall_status"] = "completed"
        self.save(state)
        return state

    def mark_blocked(self, task_id: str, reason: str) -> dict[str, Any]:
        state = self.load()
        state["tasks"][task_id]["status"] = "blocked"
        state["tasks"][task_id]["blocker_reason"] = reason
        state["meta"]["overall_status"] = "blocked"
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
    ) -> dict[str, Any]:
        state = self.load()
        meta = state["meta"]
        task = state["tasks"][task_id]
        meta["iteration"] += 1
        task["iterations"] += 1
        if not files_changed and not verification_passed:
            meta["no_progress_iterations"] += 1
        else:
            meta["no_progress_iterations"] = 0
        meta["last_fingerprint"] = fingerprint
        task["last_summary"] = summary
        task["files_changed"] = files_changed
        task["session_id"] = session_id
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
            }
        )
        self.save(state)
        return state
