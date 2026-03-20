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
    watchdog_restart_reasons: dict[str, int] = {}
    latest_watchdog_restart: dict[str, Any] | None = None
    latest_watchdog_exhausted: dict[str, Any] | None = None
    for item in history:
        event_type = item.get("event_type")
        if event_type == "blocked":
            code = str(item.get("blocker_code", "blocked"))
            blocked_by_code[code] = blocked_by_code.get(code, 0) + 1
        if event_type in {"watchdog_restart", "watchdog_exhausted"}:
            reason = str(item.get("restart_reason", "unknown"))
            watchdog_restart_reasons[reason] = watchdog_restart_reasons.get(reason, 0) + 1
            payload = {
                "timestamp": item.get("timestamp"),
                "summary": item.get("summary"),
                "restart_reason": item.get("restart_reason"),
                "restart_count": item.get("restart_count"),
                "child_pid": item.get("child_pid"),
                "child_exit_code": item.get("child_exit_code"),
            }
            if event_type == "watchdog_restart":
                if latest_watchdog_restart is None or str(item.get("timestamp", "")) >= str(
                    latest_watchdog_restart.get("timestamp", "")
                ):
                    latest_watchdog_restart = payload
            if event_type == "watchdog_exhausted":
                if latest_watchdog_exhausted is None or str(item.get("timestamp", "")) >= str(
                    latest_watchdog_exhausted.get("timestamp", "")
                ):
                    latest_watchdog_exhausted = payload
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
        "watchdog_restarts_total": sum(
            1 for item in history if item.get("event_type") == "watchdog_restart"
        ),
        "watchdog_exhausted_total": sum(
            1 for item in history if item.get("event_type") == "watchdog_exhausted"
        ),
        "watchdog_restart_reasons": watchdog_restart_reasons,
        "latest_watchdog_restart": latest_watchdog_restart,
        "latest_watchdog_exhausted": latest_watchdog_exhausted,
        "blocked_by_code": blocked_by_code,
        "tasks_skipped_by_circuit_breaker": sum(
            1
            for task in tasks.values()
            if task.get("blocker_code") == "task_failure_circuit_breaker"
        ),
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
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(build_metrics_snapshot(state), indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)
