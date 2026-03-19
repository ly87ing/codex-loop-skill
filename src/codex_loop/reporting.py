from __future__ import annotations

import json
from pathlib import Path


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
