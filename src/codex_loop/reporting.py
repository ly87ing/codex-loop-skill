from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


def _load_state(project_dir: Path) -> dict[str, Any]:
    return json.loads(
        (project_dir / ".codex-loop" / "state.json").read_text(encoding="utf-8")
    )


def _current_task_id(tasks: dict[str, dict[str, Any]]) -> str:
    return next(
        (
            task_id
            for task_id, task_state in tasks.items()
            if task_state.get("status") in {"ready", "in_progress", "blocked"}
        ),
        next(iter(tasks), "none"),
    )


def format_status_summary(project_dir: Path) -> str:
    state = _load_state(project_dir)
    project_name = state.get("meta", {}).get("project_name", project_dir.name)
    overall_status = state.get("meta", {}).get("overall_status", "unknown")
    iteration = state.get("meta", {}).get("iteration", 0)
    no_progress = state.get("meta", {}).get("no_progress_iterations", 0)
    metrics_path = project_dir / ".codex-loop" / "metrics.json"
    metrics = (
        json.loads(metrics_path.read_text(encoding="utf-8"))
        if metrics_path.exists()
        else {}
    )
    tasks = state.get("tasks", {})
    current_task_id = _current_task_id(tasks)
    current_task_state = tasks.get(current_task_id, {}) if current_task_id != "none" else {}
    last_history = state.get("history", [])[-1] if state.get("history") else None

    lines = [
        f"project: {project_name}",
        f"overall_status: {overall_status}",
        f"iteration: {iteration}",
        f"no_progress_iterations: {no_progress}",
        f"current_task: {current_task_id}",
    ]
    if current_task_state.get("session_id"):
        lines.append(f"current_task_session: {current_task_state.get('session_id')}")
    if current_task_state.get("resume_failure_reason"):
        lines.append(
            "current_task_resume_failure_reason: "
            f"{current_task_state.get('resume_failure_reason')}"
        )
    if metrics:
        lines.extend(
            [
                f"runner_failures_total: {metrics.get('runner_failures_total', 0)}",
                f"verification_failures_total: {metrics.get('verification_failures_total', 0)}",
                f"resume_fallbacks_total: {metrics.get('resume_fallbacks_total', 0)}",
            ]
        )
        if metrics.get("last_blocker_code"):
            lines.append(f"last_blocker_code: {metrics.get('last_blocker_code')}")
        if metrics.get("last_blocker_reason"):
            lines.append(f"last_blocker_reason: {metrics.get('last_blocker_reason')}")
    if last_history:
        lines.append(f"last_summary: {last_history.get('summary', '')}")
    return "\n".join(lines)


def tail_log_lines(project_dir: Path, *, lines: int, task_id: str | None = None) -> str:
    logs_dir = project_dir / ".codex-loop" / "logs"
    if not logs_dir.exists():
        msg = f"No logs directory found at {logs_dir}"
        raise FileNotFoundError(msg)
    pattern = "*.jsonl" if task_id is None else f"*-{task_id}.jsonl"
    candidates = sorted(logs_dir.glob(pattern))
    if not candidates:
        msg = f"No log files found for pattern {pattern}"
        raise FileNotFoundError(msg)
    content = candidates[-1].read_text(encoding="utf-8").splitlines()
    return "\n".join(content[-lines:])


def _history_label(entry: dict[str, Any]) -> str:
    event_type = entry.get("event_type", "event")
    if event_type == "blocked":
        return f"blocked:{entry.get('blocker_code', 'blocked')}"
    if event_type == "iteration":
        agent_status = entry.get("agent_status")
        return f"iteration:{agent_status}" if agent_status else "iteration"
    return str(event_type)


def _format_event(event: dict[str, Any]) -> str:
    timestamp = str(event.get("timestamp", "unknown-time"))
    label = str(event.get("label", "event"))
    task_id = event.get("task_id")
    task_fragment = f" task={task_id}" if task_id else ""
    summary = str(event.get("summary", "")).strip()
    return f"{timestamp} {label}{task_fragment} {summary}".rstrip()


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _iter_hook_events(project_dir: Path) -> list[dict[str, Any]]:
    hooks_dir = project_dir / ".codex-loop" / "hooks"
    if not hooks_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(hooks_dir.glob("*.jsonl")):
        event_name = path.stem
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            command = str(payload.get("command", "")).strip()
            success = bool(payload.get("success", False))
            exit_code = payload.get("exit_code")
            summary = f"{command} success={success} exit_code={exit_code}".strip()
            events.append(
                {
                    "timestamp": str(payload.get("timestamp", "unknown-time")),
                    "label": f"hook:{event_name}",
                    "event_type": "hook",
                    "task_id": payload.get("task_id"),
                    "summary": summary,
                    "source": "hook",
                }
            )
    return events


def load_events_timeline(
    project_dir: Path,
    *,
    limit: int = 20,
    task_id: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict[str, Any]]:
    state_path = project_dir / ".codex-loop" / "state.json"
    if not state_path.exists():
        msg = f"No state file found at {state_path}"
        raise FileNotFoundError(msg)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    combined: list[dict[str, Any]] = []
    for entry in state.get("history", []):
        combined.append(
            (
                {
                    "timestamp": str(entry.get("timestamp", "")),
                    "label": _history_label(entry),
                    "event_type": str(entry.get("event_type", "event")),
                    "task_id": entry.get("task_id"),
                    "blocker_code": entry.get("blocker_code"),
                    "verification_passed": entry.get("verification_passed"),
                    "agent_status": entry.get("agent_status"),
                    "summary": str(entry.get("summary", "")).strip(),
                    "source": "history",
                }
            )
        )
    combined.extend(_iter_hook_events(project_dir))
    if task_id is not None:
        combined = [entry for entry in combined if entry.get("task_id") == task_id]
    if event_type is not None:
        combined = [
            entry
            for entry in combined
            if entry.get("label") == event_type or entry.get("event_type") == event_type
        ]
    if since is not None or until is not None:
        since_ts = _parse_timestamp(since) if since is not None else None
        until_ts = _parse_timestamp(until) if until is not None else None
        filtered: list[dict[str, Any]] = []
        for entry in combined:
            try:
                event_ts = _parse_timestamp(str(entry.get("timestamp", "")))
            except ValueError:
                continue
            if since_ts is not None and event_ts < since_ts:
                continue
            if until_ts is not None and event_ts > until_ts:
                continue
            filtered.append(entry)
        combined = filtered
    if not combined:
        return []
    combined.sort(
        key=lambda entry: (
            str(entry.get("timestamp", "")),
            str(entry.get("source", "")),
            str(entry.get("label", "")),
            str(entry.get("summary", "")),
        )
    )
    return combined[-limit:]


def format_events_timeline(
    project_dir: Path,
    *,
    limit: int = 20,
    task_id: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> str:
    events = load_events_timeline(
        project_dir,
        limit=limit,
        task_id=task_id,
        event_type=event_type,
        since=since,
        until=until,
    )
    if not events:
        return "No events recorded."
    rendered = [_format_event(event) for event in events]
    return "\n".join(rendered)


def _iter_task_session_rows(
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_tasks = state.get("tasks", {})
    archived_tasks = state.get("meta", {}).get("archived_tasks", {})
    for task_id, task_state in current_tasks.items():
        rows.append(
            {
                "task_id": task_id,
                "status": task_state.get("status", "unknown"),
                "session_id": task_state.get("session_id"),
                "iterations": int(task_state.get("iterations", 0)),
                "updated_at": task_state.get("updated_at"),
                "last_summary": task_state.get("last_summary", ""),
                "resume_fallback_used": bool(
                    task_state.get("resume_fallback_used", False)
                ),
                "resume_failure_reason": task_state.get("resume_failure_reason"),
                "archived": False,
            }
        )
    for task_id, task_state in archived_tasks.items():
        rows.append(
            {
                "task_id": task_id,
                "status": task_state.get("status", "unknown"),
                "session_id": task_state.get("session_id"),
                "iterations": int(task_state.get("iterations", 0)),
                "updated_at": task_state.get("updated_at"),
                "last_summary": task_state.get("last_summary", ""),
                "resume_fallback_used": bool(
                    task_state.get("resume_fallback_used", False)
                ),
                "resume_failure_reason": task_state.get("resume_failure_reason"),
                "archived": True,
            }
        )
    rows.sort(key=lambda row: str(row.get("task_id", "")))
    return rows


def build_session_inventory(project_dir: Path) -> dict[str, Any]:
    state = _load_state(project_dir)
    tasks = state.get("tasks", {})
    current_task = _current_task_id(tasks) if tasks else "none"
    current_task_state = tasks.get(current_task, {}) if current_task != "none" else {}
    rows = _iter_task_session_rows(state)
    latest_session: dict[str, Any] | None = None
    for entry in state.get("history", []):
        session_id = entry.get("session_id")
        if not session_id:
            continue
        candidate = {
            "task_id": entry.get("task_id"),
            "session_id": session_id,
            "timestamp": entry.get("timestamp"),
            "event_type": entry.get("event_type"),
            "agent_status": entry.get("agent_status"),
            "summary": entry.get("summary"),
        }
        if latest_session is None or str(candidate.get("timestamp", "")) >= str(
            latest_session.get("timestamp", "")
        ):
            latest_session = candidate
    if latest_session is None:
        session_rows = [row for row in rows if row.get("session_id")]
        session_rows.sort(
            key=lambda row: (str(row.get("updated_at", "")), str(row.get("task_id", "")))
        )
        if session_rows:
            last_row = session_rows[-1]
            latest_session = {
                "task_id": last_row.get("task_id"),
                "session_id": last_row.get("session_id"),
                "timestamp": last_row.get("updated_at"),
                "event_type": "task_state",
                "agent_status": last_row.get("status"),
                "summary": last_row.get("last_summary"),
            }
    return {
        "project_name": state.get("meta", {}).get("project_name", project_dir.name),
        "overall_status": state.get("meta", {}).get("overall_status", "unknown"),
        "current_task": current_task,
        "current_task_session": current_task_state.get("session_id"),
        "latest_session": latest_session,
        "tasks": rows,
    }


def format_sessions_report(project_dir: Path) -> str:
    inventory = build_session_inventory(project_dir)
    lines = [
        f"project: {inventory['project_name']}",
        f"overall_status: {inventory['overall_status']}",
        f"current_task: {inventory['current_task']}",
        f"current_task_session: {inventory.get('current_task_session') or 'none'}",
        "latest_session:",
    ]
    latest_session = inventory.get("latest_session")
    if latest_session is not None:
        for key in ("task_id", "session_id", "timestamp", "event_type", "agent_status"):
            lines.append(f"{key}: {latest_session.get(key, '')}")
    lines.append("tasks:")
    for row in inventory["tasks"]:
        session_id = row.get("session_id") or "none"
        lines.append(
            f"{row['task_id']}: status={row['status']} session_id={session_id} "
            f"iterations={row['iterations']} archived={row['archived']}"
        )
    return "\n".join(lines)


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_events": len(events),
        "by_label": {},
        "by_task": {},
        "by_source": {},
        "by_blocker_code": {},
        "blocked_tasks": [],
        "latest_blocked": None,
        "latest_runner_failure": None,
        "latest_verification_failure": None,
    }
    blocked_seen: set[str] = set()
    for event in events:
        label = str(event.get("label", "unknown"))
        task_id = str(event.get("task_id", "none"))
        source = str(event.get("source", "unknown"))
        event_type = str(event.get("event_type", ""))
        summary["by_label"][label] = int(summary["by_label"].get(label, 0)) + 1
        summary["by_task"][task_id] = int(summary["by_task"].get(task_id, 0)) + 1
        summary["by_source"][source] = int(summary["by_source"].get(source, 0)) + 1
        if event_type == "runner_failure":
            latest_runner_failure = summary["latest_runner_failure"]
            if latest_runner_failure is None or str(event.get("timestamp", "")) >= str(
                latest_runner_failure.get("timestamp", "")
            ):
                summary["latest_runner_failure"] = {
                    "task_id": event.get("task_id"),
                    "timestamp": event.get("timestamp"),
                    "summary": event.get("summary"),
                }
        if event_type == "iteration" and event.get("verification_passed") is False:
            latest_verification_failure = summary["latest_verification_failure"]
            if latest_verification_failure is None or str(event.get("timestamp", "")) >= str(
                latest_verification_failure.get("timestamp", "")
            ):
                summary["latest_verification_failure"] = {
                    "task_id": event.get("task_id"),
                    "timestamp": event.get("timestamp"),
                    "summary": event.get("summary"),
                }
        blocker_code = event.get("blocker_code")
        if blocker_code:
            blocker_key = str(blocker_code)
            summary["by_blocker_code"][blocker_key] = (
                int(summary["by_blocker_code"].get(blocker_key, 0)) + 1
            )
            if task_id != "none" and task_id not in blocked_seen:
                blocked_seen.add(task_id)
                summary["blocked_tasks"].append(task_id)
            latest_blocked = summary["latest_blocked"]
            if latest_blocked is None or str(event.get("timestamp", "")) >= str(
                latest_blocked.get("timestamp", "")
            ):
                summary["latest_blocked"] = {
                    "task_id": event.get("task_id"),
                    "blocker_code": blocker_key,
                    "timestamp": event.get("timestamp"),
                    "summary": event.get("summary"),
                }
    return summary


def format_events_summary(events: list[dict[str, Any]]) -> str:
    summary = summarize_events(events)
    lines = [f"total_events: {summary['total_events']}"]
    for section_name in ("by_label", "by_task", "by_source", "by_blocker_code"):
        lines.append(f"{section_name}:")
        entries = summary[section_name]
        for key in sorted(entries):
            lines.append(f"{key}: {entries[key]}")
    lines.append("blocked_tasks:")
    for task_id in summary["blocked_tasks"]:
        lines.append(task_id)
    lines.append("latest_blocked:")
    latest_blocked = summary["latest_blocked"]
    if latest_blocked is not None:
        for key in ("task_id", "blocker_code", "timestamp", "summary"):
            lines.append(f"{key}: {latest_blocked.get(key, '')}")
    for field_name in ("latest_runner_failure", "latest_verification_failure"):
        lines.append(f"{field_name}:")
        payload = summary[field_name]
        if payload is not None:
            for key in ("task_id", "timestamp", "summary"):
                lines.append(f"{key}: {payload.get(key, '')}")
    return "\n".join(lines)
