from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def build_metrics_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    history = state.get("history", [])
    tasks = state.get("tasks", {})
    meta = state.get("meta", {})
    blocked_by_code: dict[str, int] = {}
    for item in history:
        if item.get("event_type") != "blocked":
            continue
        code = str(item.get("blocker_code", "blocked"))
        blocked_by_code[code] = blocked_by_code.get(code, 0) + 1
    last_blocker = meta.get("last_blocker") or {}
    return {
        "generated_at": _now(),
        "overall_status": meta.get("overall_status", "unknown"),
        "total_iterations": int(meta.get("iteration", 0)),
        "history_entries": len(history),
        "tasks_total": len(tasks),
        "tasks_done": sum(1 for task in tasks.values() if task.get("status") == "done"),
        "tasks_blocked": sum(
            1 for task in tasks.values() if task.get("status") == "blocked"
        ),
        "runner_failures_total": sum(
            1 for item in history if item.get("event_type") == "runner_failure"
        ),
        "verification_failures_total": sum(
            1
            for item in history
            if item.get("event_type") == "iteration"
            and not item.get("verification_passed", False)
        ),
        "resume_fallbacks_total": sum(
            1 for item in history if item.get("resume_fallback_used", False)
        ),
        "blocked_events_total": sum(
            1 for item in history if item.get("event_type") == "blocked"
        ),
        "blocked_by_code": blocked_by_code,
        "consecutive_runner_failures": int(
            meta.get("consecutive_runner_failures", 0)
        ),
        "consecutive_verification_failures": int(
            meta.get("consecutive_verification_failures", 0)
        ),
        "last_blocker_code": last_blocker.get("code"),
        "last_blocker_reason": last_blocker.get("reason"),
        "last_error": meta.get("last_error"),
    }


def write_metrics_snapshot(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_metrics_snapshot(state), indent=2),
        encoding="utf-8",
    )
