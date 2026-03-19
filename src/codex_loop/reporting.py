from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


def format_status_summary(project_dir: Path) -> str:
    state = json.loads(
        (project_dir / ".codex-loop" / "state.json").read_text(encoding="utf-8")
    )
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
    current_task_id = next(
        (
            task_id
            for task_id, task_state in tasks.items()
            if task_state.get("status") in {"ready", "in_progress", "blocked"}
        ),
        next(iter(tasks), "none"),
    )
    last_history = state.get("history", [])[-1] if state.get("history") else None

    lines = [
        f"project: {project_name}",
        f"overall_status: {overall_status}",
        f"iteration: {iteration}",
        f"no_progress_iterations: {no_progress}",
        f"current_task: {current_task_id}",
    ]
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
