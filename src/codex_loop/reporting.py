from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any


def _load_state(project_dir: Path) -> dict[str, Any]:
    try:
        return json.loads(
            (project_dir / ".codex-loop" / "state.json").read_text(encoding="utf-8")
        )
    except Exception:  # noqa: BLE001
        return {"tasks": {}, "history": [], "meta": {}}


def _current_task_id(tasks: dict[str, dict[str, Any]]) -> str:
    return next(
        (
            task_id
            for task_id, task_state in tasks.items()
            if task_state.get("status") in {"ready", "in_progress", "blocked"}
        ),
        next(iter(tasks), "none"),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _latest_task_artifact(
    project_dir: Path,
    *,
    directory_name: str,
    task_id: str,
    pattern: str,
) -> str | None:
    directory = project_dir / ".codex-loop" / directory_name
    if not directory.exists():
        return None
    candidates = sorted(directory.glob(pattern))
    if not candidates:
        return None
    return str(candidates[-1])


def _task_artifacts(project_dir: Path, task_id: str) -> dict[str, str | None]:
    run_path = project_dir / ".codex-loop" / "runs" / f"{task_id}-last.json"
    return {
        "prompt": _latest_task_artifact(
            project_dir,
            directory_name="prompts",
            task_id=task_id,
            pattern=f"*-{task_id}.txt",
        ),
        "log": _latest_task_artifact(
            project_dir,
            directory_name="logs",
            task_id=task_id,
            pattern=f"*-{task_id}.jsonl",
        ),
        "run": str(run_path) if run_path.exists() else None,
    }


def _read_text_preview(path: str | None, *, lines: int, from_end: bool = False) -> str | None:
    if path is None:
        return None
    try:
        text_lines = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return None
    if not text_lines:
        return ""
    selected = text_lines[-lines:] if from_end else text_lines[:lines]
    return "\n".join(selected)


def _read_json_payload(path: str | None) -> Any:
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _is_blocked_snapshot(snapshot: dict[str, Any]) -> bool:
    return bool(
        snapshot.get("overall_status") == "blocked" or snapshot.get("last_blocker_code")
    )


def _snapshot_group_value(snapshot: dict[str, Any], group_by: str) -> str:
    if group_by == "task":
        return str(snapshot.get("task_id", "none"))
    if group_by == "status":
        return str(snapshot.get("overall_status", "unknown"))
    if group_by == "selection":
        return str(snapshot.get("selection", "unknown"))
    if group_by == "blocker":
        return str(snapshot.get("last_blocker_code") or "none")
    msg = f"Unsupported snapshot group_by value: {group_by}"
    raise ValueError(msg)


def _snapshot_export_filters(entry: dict[str, Any]) -> dict[str, Any]:
    filters = entry.get("filters")
    return filters if isinstance(filters, dict) else {}


def _snapshot_export_group_value(entry: dict[str, Any], group_by: str) -> str:
    filters = _snapshot_export_filters(entry)
    if group_by == "task":
        return str(filters.get("task_id") or "all")
    if group_by == "status":
        return str(filters.get("status") or "all")
    if group_by == "blocker":
        return str(filters.get("blocker_code") or "none")
    if group_by == "render":
        return str(entry.get("render_format") or "unknown")
    if group_by == "summary":
        return "summary" if bool(entry.get("summary")) else "list"
    msg = f"Unsupported snapshot export group_by value: {group_by}"
    raise ValueError(msg)


def load_snapshot_exports_manifest(
    exports_dir: Path,
    *,
    task_id: str | None = None,
    status: str | None = None,
    blocker_code: str | None = None,
    watchdog_phase: str | None = None,
    latest: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    manifest_path = exports_dir.resolve() / "manifest.json"
    if not manifest_path.exists():
        msg = f"No snapshot export manifest found at {manifest_path}"
        raise FileNotFoundError(msg)
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        msg = f"Corrupt snapshot export manifest at {manifest_path}: {exc}"
        raise ValueError(msg) from exc
    exports = manifest_data.get("exports", [])
    if not isinstance(exports, list):
        return []
    filtered = [item for item in exports if isinstance(item, dict)]
    if task_id is not None:
        filtered = [
            item for item in filtered if _snapshot_export_filters(item).get("task_id") == task_id
        ]
    if status is not None:
        filtered = [
            item for item in filtered if _snapshot_export_filters(item).get("status") == status
        ]
    if blocker_code is not None:
        filtered = [
            item
            for item in filtered
            if _snapshot_export_filters(item).get("blocker_code") == blocker_code
        ]
    if watchdog_phase is not None:
        filtered = [
            item
            for item in filtered
            if _snapshot_export_filters(item).get("watchdog_phase") == watchdog_phase
        ]
    filtered.sort(key=lambda item: str(item.get("generated_at", "")))
    if latest:
        return filtered[-1:] if filtered else []
    if limit is not None:
        return filtered[-limit:]
    return filtered


def format_snapshot_exports_report(
    exports_dir: Path,
    *,
    task_id: str | None = None,
    status: str | None = None,
    blocker_code: str | None = None,
    watchdog_phase: str | None = None,
    latest: bool = False,
    limit: int | None = None,
) -> str:
    exports = load_snapshot_exports_manifest(
        exports_dir,
        task_id=task_id,
        status=status,
        blocker_code=blocker_code,
        watchdog_phase=watchdog_phase,
        latest=latest,
        limit=limit,
    )
    if not exports:
        return "No snapshot exports recorded."
    lines = [f"exports_dir: {exports_dir.resolve()}", f"count: {len(exports)}", "exports:"]
    for entry in exports:
        filters = _snapshot_export_filters(entry)
        lines.append(
            f"{entry.get('generated_at', '')} "
            f"render={entry.get('render_format', '')} "
            f"summary={entry.get('summary', False)} "
            f"group_by={entry.get('group_by') or 'none'} "
            f"snapshot_count={entry.get('snapshot_count', 0)} "
            f"task={filters.get('task_id') or 'all'} "
            f"status={filters.get('status') or 'all'} "
            f"blocker={filters.get('blocker_code') or 'none'} "
            f"watchdog={filters.get('watchdog_phase') or 'none'} "
            f"path={entry.get('export_path', '')}"
        )
    return "\n".join(lines)


def _base_snapshot_exports_summary(exports: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_exports": len(exports),
        "by_task": {},
        "by_status": {},
        "by_blocker_code": {},
        "by_watchdog_phase": {},
        "by_render_format": {},
        "by_summary": {},
        "latest_export": None,
    }
    for entry in exports:
        filters = _snapshot_export_filters(entry)
        task_key = str(filters.get("task_id") or "all")
        status_key = str(filters.get("status") or "all")
        blocker_key = str(filters.get("blocker_code") or "none")
        watchdog_key = str(filters.get("watchdog_phase") or "none")
        render_key = str(entry.get("render_format") or "unknown")
        summary_key = "summary" if bool(entry.get("summary")) else "list"
        timestamp = str(entry.get("generated_at", ""))
        summary["by_task"][task_key] = int(summary["by_task"].get(task_key, 0)) + 1
        summary["by_status"][status_key] = int(summary["by_status"].get(status_key, 0)) + 1
        summary["by_blocker_code"][blocker_key] = (
            int(summary["by_blocker_code"].get(blocker_key, 0)) + 1
        )
        summary["by_watchdog_phase"][watchdog_key] = (
            int(summary["by_watchdog_phase"].get(watchdog_key, 0)) + 1
        )
        summary["by_render_format"][render_key] = (
            int(summary["by_render_format"].get(render_key, 0)) + 1
        )
        summary["by_summary"][summary_key] = int(summary["by_summary"].get(summary_key, 0)) + 1
        latest_export = summary["latest_export"]
        if latest_export is None or timestamp >= str(latest_export.get("generated_at", "")):
            summary["latest_export"] = {
                "generated_at": entry.get("generated_at"),
                "export_path": entry.get("export_path"),
                "render_format": entry.get("render_format"),
                "summary": entry.get("summary"),
                "task_id": filters.get("task_id"),
                "status": filters.get("status"),
                "blocker_code": filters.get("blocker_code"),
                "watchdog_phase": filters.get("watchdog_phase"),
            }
    return summary


def summarize_snapshot_exports(
    exports: list[dict[str, Any]],
    *,
    group_by: str | None = None,
) -> dict[str, Any]:
    if group_by is not None:
        grouped_counts: dict[str, int] = {}
        for entry in exports:
            key = _snapshot_export_group_value(entry, group_by)
            grouped_counts[key] = int(grouped_counts.get(key, 0)) + 1
        base_summary = _base_snapshot_exports_summary(exports)
        return {
            "total_exports": base_summary["total_exports"],
            "group_by": group_by,
            "grouped_counts": grouped_counts,
            "latest_export": base_summary["latest_export"],
        }
    return _base_snapshot_exports_summary(exports)


def format_snapshot_exports_summary(
    exports: list[dict[str, Any]],
    *,
    group_by: str | None = None,
) -> str:
    summary = summarize_snapshot_exports(exports, group_by=group_by)
    lines = [f"total_exports: {summary['total_exports']}"]
    if group_by is not None:
        lines.append(f"group_by: {group_by}")
        lines.append("grouped_counts:")
        entries = summary["grouped_counts"]
        for key in sorted(entries):
            lines.append(f"{key}: {entries[key]}")
    else:
        for section_name in (
            "by_task",
            "by_status",
            "by_blocker_code",
            "by_watchdog_phase",
            "by_render_format",
            "by_summary",
        ):
            lines.append(f"{section_name}:")
            entries = summary[section_name]
            for key in sorted(entries):
                lines.append(f"{key}: {entries[key]}")
    lines.append("latest_export:")
    payload = summary["latest_export"]
    if payload is not None:
        for key, value in payload.items():
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def load_snapshots_index(
    snapshot_dir: Path,
    *,
    task_id: str | None = None,
    status: str | None = None,
    blocker_code: str | None = None,
    watchdog_phase: str | None = None,
    since: str | None = None,
    until: str | None = None,
    sort_order: str = "oldest",
    limit: int | None = None,
    latest: bool = False,
    latest_blocked: bool = False,
) -> list[dict[str, Any]]:
    if latest and latest_blocked:
        msg = "Use either latest or latest_blocked, not both."
        raise ValueError(msg)
    index_path = snapshot_dir.resolve() / "index.json"
    if not index_path.exists():
        msg = f"No snapshot index found at {index_path}"
        raise FileNotFoundError(msg)
    try:
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        msg = f"Corrupt snapshot index at {index_path}: {exc}"
        raise ValueError(msg) from exc
    snapshots = index_data.get("snapshots", [])
    if not isinstance(snapshots, list):
        return []
    filtered = [item for item in snapshots if isinstance(item, dict)]
    if task_id is not None:
        filtered = [item for item in filtered if item.get("task_id") == task_id]
    if status is not None:
        filtered = [item for item in filtered if item.get("overall_status") == status]
    if blocker_code is not None:
        filtered = [item for item in filtered if item.get("last_blocker_code") == blocker_code]
    if watchdog_phase is not None:
        filtered = [item for item in filtered if item.get("watchdog_phase") == watchdog_phase]
    if since is not None or until is not None:
        since_ts = _parse_timestamp(since) if since is not None else None
        until_ts = _parse_timestamp(until) if until is not None else None
        time_filtered: list[dict[str, Any]] = []
        for item in filtered:
            try:
                snapshot_ts = _parse_timestamp(str(item.get("generated_at", "")))
            except ValueError:
                continue
            if since_ts is not None and snapshot_ts < since_ts:
                continue
            if until_ts is not None and snapshot_ts > until_ts:
                continue
            time_filtered.append(item)
        filtered = time_filtered
    filtered.sort(key=lambda item: str(item.get("generated_at", "")))
    if latest_blocked:
        blocked = [item for item in filtered if _is_blocked_snapshot(item)]
        filtered = blocked[-1:] if blocked else []
    elif latest:
        filtered = filtered[-1:] if filtered else []
    elif limit is not None:
        filtered = filtered[-limit:]
    if sort_order == "newest":
        filtered = list(reversed(filtered))
    return filtered


def format_snapshots_report(
    snapshot_dir: Path,
    *,
    task_id: str | None = None,
    status: str | None = None,
    blocker_code: str | None = None,
    watchdog_phase: str | None = None,
    since: str | None = None,
    until: str | None = None,
    sort_order: str = "oldest",
    limit: int | None = None,
    latest: bool = False,
    latest_blocked: bool = False,
) -> str:
    snapshots = load_snapshots_index(
        snapshot_dir,
        task_id=task_id,
        status=status,
        blocker_code=blocker_code,
        watchdog_phase=watchdog_phase,
        since=since,
        until=until,
        sort_order=sort_order,
        limit=limit,
        latest=latest,
        latest_blocked=latest_blocked,
    )
    if not snapshots:
        return "No snapshots recorded."
    lines = [f"snapshot_dir: {snapshot_dir.resolve()}", f"count: {len(snapshots)}", "snapshots:"]
    for snapshot in snapshots:
        lines.append(
            f"{snapshot.get('generated_at', '')} "
            f"task={snapshot.get('task_id', '')} "
            f"selection={snapshot.get('selection', '')} "
            f"status={snapshot.get('overall_status', '')} "
            f"blocker={snapshot.get('last_blocker_code') or 'none'} "
            f"watchdog={snapshot.get('watchdog_phase') or 'none'} "
            f"path={snapshot.get('snapshot_path', '')}"
        )
    return "\n".join(lines)


def _base_snapshots_summary(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_snapshots": len(snapshots),
        "by_task": {},
        "by_status": {},
        "by_selection": {},
        "by_blocker_code": {},
        "by_watchdog_phase": {},
        "latest_snapshot": None,
        "latest_blocked": None,
        "latest_watchdog_alert": None,
    }
    for snapshot in snapshots:
        task_id = str(snapshot.get("task_id", "none"))
        status = str(snapshot.get("overall_status", "unknown"))
        selection = str(snapshot.get("selection", "unknown"))
        timestamp = str(snapshot.get("generated_at", ""))
        watchdog_phase = snapshot.get("watchdog_phase")
        summary["by_task"][task_id] = int(summary["by_task"].get(task_id, 0)) + 1
        summary["by_status"][status] = int(summary["by_status"].get(status, 0)) + 1
        summary["by_selection"][selection] = int(summary["by_selection"].get(selection, 0)) + 1

        blocker_code = snapshot.get("last_blocker_code")
        if blocker_code:
            blocker_key = str(blocker_code)
            summary["by_blocker_code"][blocker_key] = (
                int(summary["by_blocker_code"].get(blocker_key, 0)) + 1
            )
        if watchdog_phase:
            watchdog_key = str(watchdog_phase)
            summary["by_watchdog_phase"][watchdog_key] = (
                int(summary["by_watchdog_phase"].get(watchdog_key, 0)) + 1
            )

        latest_snapshot = summary["latest_snapshot"]
        if latest_snapshot is None or timestamp >= str(latest_snapshot.get("generated_at", "")):
            summary["latest_snapshot"] = {
                "task_id": snapshot.get("task_id"),
                "overall_status": snapshot.get("overall_status"),
                "selection": snapshot.get("selection"),
                "generated_at": snapshot.get("generated_at"),
                "snapshot_path": snapshot.get("snapshot_path"),
            }

        if status == "blocked" or blocker_code:
            latest_blocked = summary["latest_blocked"]
            if latest_blocked is None or timestamp >= str(
                latest_blocked.get("generated_at", "")
            ):
                summary["latest_blocked"] = {
                    "task_id": snapshot.get("task_id"),
                    "blocker_code": blocker_code,
                    "generated_at": snapshot.get("generated_at"),
                    "snapshot_path": snapshot.get("snapshot_path"),
                }
        if watchdog_phase in {"restarting", "exhausted"}:
            latest_watchdog_alert = summary["latest_watchdog_alert"]
            if latest_watchdog_alert is None or timestamp >= str(
                latest_watchdog_alert.get("generated_at", "")
            ):
                summary["latest_watchdog_alert"] = {
                    "task_id": snapshot.get("task_id"),
                    "watchdog_phase": watchdog_phase,
                    "watchdog_restart_count": snapshot.get("watchdog_restart_count"),
                    "watchdog_last_restart_reason": snapshot.get(
                        "watchdog_last_restart_reason"
                    ),
                    "latest_watchdog_exhausted_reason": snapshot.get(
                        "latest_watchdog_exhausted_reason"
                    ),
                    "generated_at": snapshot.get("generated_at"),
                    "snapshot_path": snapshot.get("snapshot_path"),
                }
    return summary


def summarize_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    group_by: str | None = None,
) -> dict[str, Any]:
    if group_by is not None:
        grouped_counts: dict[str, int] = {}
        for snapshot in snapshots:
            key = _snapshot_group_value(snapshot, group_by)
            grouped_counts[key] = int(grouped_counts.get(key, 0)) + 1
        base_summary = _base_snapshots_summary(snapshots)
        return {
            "total_snapshots": base_summary["total_snapshots"],
            "group_by": group_by,
            "grouped_counts": grouped_counts,
            "latest_snapshot": base_summary["latest_snapshot"],
            "latest_blocked": base_summary["latest_blocked"],
            "latest_watchdog_alert": base_summary["latest_watchdog_alert"],
        }
    return _base_snapshots_summary(snapshots)


def format_snapshots_summary(
    snapshots: list[dict[str, Any]],
    *,
    group_by: str | None = None,
) -> str:
    summary = summarize_snapshots(snapshots, group_by=group_by)
    lines = [f"total_snapshots: {summary['total_snapshots']}"]
    if group_by is not None:
        lines.append(f"group_by: {group_by}")
        lines.append("grouped_counts:")
        entries = summary["grouped_counts"]
        for key in sorted(entries):
            lines.append(f"{key}: {entries[key]}")
    else:
        for section_name in (
            "by_task",
            "by_status",
            "by_selection",
            "by_blocker_code",
            "by_watchdog_phase",
        ):
            lines.append(f"{section_name}:")
            entries = summary[section_name]
            for key in sorted(entries):
                lines.append(f"{key}: {entries[key]}")
    for field_name in ("latest_snapshot", "latest_blocked", "latest_watchdog_alert"):
        lines.append(f"{field_name}:")
        payload = summary[field_name]
        if payload is not None:
            for key, value in payload.items():
                lines.append(f"{key}: {value}")
    return "\n".join(lines)


def build_status_snapshot(project_dir: Path) -> dict[str, Any]:
    state = _load_state(project_dir)
    project_name = state.get("meta", {}).get("project_name", project_dir.name)
    overall_status = state.get("meta", {}).get("overall_status", "unknown")
    iteration = state.get("meta", {}).get("iteration", 0)
    no_progress = state.get("meta", {}).get("no_progress_iterations", 0)
    metrics_path = project_dir / ".codex-loop" / "metrics.json"
    metrics: dict[str, Any] = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    tasks = state.get("tasks", {})
    current_task_id = _current_task_id(tasks)
    current_task_state = tasks.get(current_task_id, {}) if current_task_id != "none" else {}
    last_history = state.get("history", [])[-1] if state.get("history") else None
    watchdog_candidates = [
        project_dir / ".codex-loop" / "daemon-watchdog.json",
        project_dir / ".codex-loop" / "service-watchdog.json",
    ]
    watchdog: dict[str, Any] = {}
    for candidate in watchdog_candidates:
        if candidate.exists():
            try:
                watchdog = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
            break
    return {
        "project": project_name,
        "overall_status": overall_status,
        "iteration": iteration,
        "no_progress_iterations": no_progress,
        "current_task": current_task_id,
        "current_task_session": current_task_state.get("session_id"),
        "current_task_resume_failure_reason": current_task_state.get(
            "resume_failure_reason"
        ),
        "runner_failures_total": metrics.get("runner_failures_total", 0),
        "verification_failures_total": metrics.get("verification_failures_total", 0),
        "resume_fallbacks_total": metrics.get("resume_fallbacks_total", 0),
        "last_blocker_code": metrics.get("last_blocker_code"),
        "last_blocker_reason": metrics.get("last_blocker_reason"),
        "last_summary": last_history.get("summary", "") if last_history else "",
        "watchdog_phase": watchdog.get("phase"),
        "watchdog_restart_count": watchdog.get("restart_count"),
        "watchdog_last_restart_reason": watchdog.get("last_restart_reason"),
    }


def format_status_summary(project_dir: Path) -> str:
    snapshot = build_status_snapshot(project_dir)

    lines = [
        f"project: {snapshot['project']}",
        f"overall_status: {snapshot['overall_status']}",
        f"iteration: {snapshot['iteration']}",
        f"no_progress_iterations: {snapshot['no_progress_iterations']}",
        f"current_task: {snapshot['current_task']}",
    ]
    if snapshot.get("current_task_session"):
        lines.append(f"current_task_session: {snapshot.get('current_task_session')}")
    if snapshot.get("current_task_resume_failure_reason"):
        lines.append(
            "current_task_resume_failure_reason: "
            f"{snapshot.get('current_task_resume_failure_reason')}"
        )
    lines.extend(
        [
            f"runner_failures_total: {snapshot.get('runner_failures_total', 0)}",
            f"verification_failures_total: {snapshot.get('verification_failures_total', 0)}",
            f"resume_fallbacks_total: {snapshot.get('resume_fallbacks_total', 0)}",
        ]
    )
    if snapshot.get("last_blocker_code"):
        lines.append(f"last_blocker_code: {snapshot.get('last_blocker_code')}")
    if snapshot.get("last_blocker_reason"):
        lines.append(f"last_blocker_reason: {snapshot.get('last_blocker_reason')}")
    if snapshot.get("last_summary"):
        lines.append(f"last_summary: {snapshot.get('last_summary')}")
    if snapshot.get("watchdog_phase"):
        lines.append(f"watchdog_phase: {snapshot.get('watchdog_phase')}")
    if snapshot.get("watchdog_restart_count") is not None:
        lines.append(
            f"watchdog_restart_count: {snapshot.get('watchdog_restart_count')}"
        )
    if snapshot.get("watchdog_last_restart_reason"):
        lines.append(
            "watchdog_last_restart_reason: "
            f"{snapshot.get('watchdog_last_restart_reason')}"
        )
    return "\n".join(lines)


def _classify_health(
    *,
    status_snapshot: dict[str, Any],
    doctor_errors: list[str],
    daemon: dict[str, Any],
    service: dict[str, Any] | None,
    events_summary: dict[str, Any] | None,
    snapshots_summary: dict[str, Any] | None,
) -> str:
    if doctor_errors:
        return "error"
    if status_snapshot.get("overall_status") == "blocked":
        return "degraded"
    if status_snapshot.get("watchdog_phase") == "exhausted":
        return "degraded"
    if daemon.get("running") and (
        daemon.get("dead_process")
        or daemon.get("stale_heartbeat")
        or daemon.get("watchdog_phase") == "exhausted"
    ):
        return "degraded"
    if service is not None and service.get("installed") and (
        service.get("missing_heartbeat")
        or service.get("stale_heartbeat")
        or service.get("watchdog_phase") == "exhausted"
    ):
        return "degraded"
    if events_summary is not None and events_summary.get("latest_watchdog_exhausted") is not None:
        return "degraded"
    if snapshots_summary is not None and snapshots_summary.get("latest_watchdog_alert") is not None:
        return "degraded"
    return "ok"


def build_health_snapshot(
    project_dir: Path,
    *,
    events_limit: int = 20,
    snapshot_dir: Path | None = None,
    exports_dir: Path | None = None,
) -> dict[str, Any]:
    from .daemon_manager import daemon_status
    from .doctor import run_doctor

    project_dir = project_dir.resolve()
    status_snapshot = build_status_snapshot(project_dir)
    doctor_report = run_doctor(project_dir, repair=False)
    daemon = daemon_status(project_dir)
    service: dict[str, Any] | None = None
    if sys.platform == "darwin":
        from .service_manager import service_status

        service = service_status(project_dir)
    events_summary: dict[str, Any] | None
    try:
        events_summary = summarize_events(
            load_events_timeline(project_dir, limit=events_limit)
        )
    except FileNotFoundError:
        events_summary = None

    resolved_snapshot_dir = (
        snapshot_dir.resolve()
        if snapshot_dir is not None
        else (project_dir / "snapshots").resolve()
    )
    snapshots_summary: dict[str, Any] | None = None
    if (resolved_snapshot_dir / "index.json").exists():
        snapshots_summary = summarize_snapshots(
            load_snapshots_index(resolved_snapshot_dir)
        )

    resolved_exports_dir = (
        exports_dir.resolve()
        if exports_dir is not None
        else (project_dir / "snapshot-reports").resolve()
    )
    snapshot_exports_summary: dict[str, Any] | None = None
    if (resolved_exports_dir / "manifest.json").exists():
        snapshot_exports_summary = summarize_snapshot_exports(
            load_snapshot_exports_manifest(resolved_exports_dir)
        )

    health = _classify_health(
        status_snapshot=status_snapshot,
        doctor_errors=doctor_report.errors,
        daemon=daemon,
        service=service,
        events_summary=events_summary,
        snapshots_summary=snapshots_summary,
    )
    return {
        "project": status_snapshot.get("project"),
        "project_dir": str(project_dir),
        "health": health,
        "status": status_snapshot,
        "doctor": {
            "errors": list(doctor_report.errors),
            "warnings": list(doctor_report.warnings),
            "checked": list(doctor_report.checked),
        },
        "events": events_summary,
        "snapshots": snapshots_summary,
        "snapshot_exports": snapshot_exports_summary,
        "daemon": daemon,
        "service": service,
        "snapshot_dir": str(resolved_snapshot_dir),
        "snapshot_exports_dir": str(resolved_exports_dir),
    }


def format_health_report(
    project_dir: Path,
    *,
    events_limit: int = 20,
    snapshot_dir: Path | None = None,
    exports_dir: Path | None = None,
) -> str:
    payload = build_health_snapshot(
        project_dir,
        events_limit=events_limit,
        snapshot_dir=snapshot_dir,
        exports_dir=exports_dir,
    )
    lines = [
        f"project: {payload.get('project')}",
        f"health: {payload.get('health')}",
        f"overall_status: {payload['status'].get('overall_status')}",
        f"current_task: {payload['status'].get('current_task')}",
        f"doctor_errors: {len(payload['doctor'].get('errors', []))}",
        f"doctor_warnings: {len(payload['doctor'].get('warnings', []))}",
    ]
    daemon = payload.get("daemon") or {}
    lines.append(
        "daemon: "
        f"running={daemon.get('running')} "
        f"phase={daemon.get('phase') or 'none'} "
        f"watchdog_phase={daemon.get('watchdog_phase') or 'none'}"
    )
    service = payload.get("service")
    if isinstance(service, dict):
        lines.append(
            "service: "
            f"installed={service.get('installed')} "
            f"loaded={service.get('loaded')} "
            f"healthy={service.get('healthy')}"
        )
    events = payload.get("events") or {}
    lines.append(f"events_total: {events.get('total_events', 0)}")
    latest_blocked = events.get("latest_blocked") if isinstance(events, dict) else None
    if latest_blocked is not None:
        lines.append(
            f"latest_blocked_code: {latest_blocked.get('blocker_code') or 'none'}"
        )
    latest_watchdog_exhausted = (
        events.get("latest_watchdog_exhausted") if isinstance(events, dict) else None
    )
    if latest_watchdog_exhausted is not None:
        lines.append(
            "latest_watchdog_restart_reason: "
            f"{latest_watchdog_exhausted.get('restart_reason') or 'none'}"
        )
    snapshots = payload.get("snapshots") or {}
    if isinstance(snapshots, dict):
        lines.append(f"snapshots_total: {snapshots.get('total_snapshots', 0)}")
        latest_watchdog_alert = snapshots.get("latest_watchdog_alert")
        if latest_watchdog_alert is not None:
            lines.append(
                "snapshot_watchdog_phase: "
                f"{latest_watchdog_alert.get('watchdog_phase') or 'none'}"
            )
    snapshot_exports = payload.get("snapshot_exports") or {}
    if isinstance(snapshot_exports, dict):
        lines.append(
            f"snapshot_exports_total: {snapshot_exports.get('total_exports', 0)}"
        )
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
    try:
        content = candidates[-1].read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        msg = f"Failed to read log file {candidates[-1]}: {exc}"
        raise OSError(msg) from exc
    return "\n".join(content[-lines:])


def _history_label(entry: dict[str, Any]) -> str:
    event_type = entry.get("event_type", "event")
    if event_type == "blocked":
        return f"blocked:{entry.get('blocker_code', 'blocked')}"
    if event_type == "iteration":
        agent_status = entry.get("agent_status")
        return f"iteration:{agent_status}" if agent_status else "iteration"
    if event_type in {"watchdog_restart", "watchdog_exhausted"}:
        restart_reason = entry.get("restart_reason")
        return f"{event_type}:{restart_reason}" if restart_reason else str(event_type)
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
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in raw_text.splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
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


def _history_timeline_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    next_order = 0
    for entry in state.get("history", []):
        entries.append(
            {
                "_order": next_order,
                "timestamp": str(entry.get("timestamp", "")),
                "label": _history_label(entry),
                "event_type": str(entry.get("event_type", "event")),
                "task_id": entry.get("task_id"),
                "blocker_code": entry.get("blocker_code"),
                "restart_reason": entry.get("restart_reason"),
                "restart_count": entry.get("restart_count"),
                "child_pid": entry.get("child_pid"),
                "child_exit_code": entry.get("child_exit_code"),
                "verification_passed": entry.get("verification_passed"),
                "agent_status": entry.get("agent_status"),
                "summary": str(entry.get("summary", "")).strip(),
                "source": "history",
            }
        )
        next_order += 1
    return entries


def _select_recent_events(
    combined: list[dict[str, Any]],
    *,
    limit: int,
    task_id: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict[str, Any]]:
    filtered = list(combined)
    if task_id is not None:
        filtered = [entry for entry in filtered if entry.get("task_id") == task_id]
    if event_type is not None:
        filtered = [
            entry
            for entry in filtered
            if entry.get("label") == event_type or entry.get("event_type") == event_type
        ]
    if since is not None or until is not None:
        since_ts = _parse_timestamp(since) if since is not None else None
        until_ts = _parse_timestamp(until) if until is not None else None
        time_filtered: list[dict[str, Any]] = []
        for entry in filtered:
            try:
                event_ts = _parse_timestamp(str(entry.get("timestamp", "")))
            except ValueError:
                continue
            if since_ts is not None and event_ts < since_ts:
                continue
            if until_ts is not None and event_ts > until_ts:
                continue
            time_filtered.append(entry)
        filtered = time_filtered
    if not filtered:
        return []
    filtered.sort(
        key=lambda entry: (
            str(entry.get("timestamp", "")),
            int(entry.get("_order", 0)),
        )
    )
    selected = filtered[-limit:]
    for entry in selected:
        entry.pop("_order", None)
    return selected


def _load_recent_watchdog_events(project_dir: Path, *, limit: int) -> list[dict[str, Any]]:
    state = _load_state(project_dir)
    history_events = _history_timeline_entries(state)
    watchdog_events = [
        entry
        for entry in history_events
        if entry.get("event_type") in {"watchdog_restart", "watchdog_exhausted"}
    ]
    return _select_recent_events(watchdog_events, limit=limit)


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
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        msg = f"Corrupt state file at {state_path}: {exc}"
        raise ValueError(msg) from exc
    combined = _history_timeline_entries(state)
    next_order = len(combined)
    hook_events = _iter_hook_events(project_dir)
    for entry in hook_events:
        event = dict(entry)
        event["_order"] = next_order
        combined.append(event)
        next_order += 1
    return _select_recent_events(
        combined,
        limit=limit,
        task_id=task_id,
        event_type=event_type,
        since=since,
        until=until,
    )


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
    project_dir: Path,
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
                "artifacts": _task_artifacts(project_dir, task_id),
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
                "artifacts": _task_artifacts(project_dir, task_id),
            }
        )
    rows.sort(key=lambda row: str(row.get("task_id", "")))
    return rows


def build_session_inventory(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    state = _load_state(project_dir)
    tasks = state.get("tasks", {})
    current_task = _current_task_id(tasks) if tasks else "none"
    current_task_state = tasks.get(current_task, {}) if current_task != "none" else {}
    rows = _iter_task_session_rows(project_dir, state)
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
            "artifacts": _task_artifacts(project_dir, str(entry.get("task_id"))),
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
                "artifacts": dict(last_row.get("artifacts", {})),
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
        artifacts = latest_session.get("artifacts", {})
        for key in ("prompt", "log", "run"):
            lines.append(f"{key}: {artifacts.get(key) or 'none'}")
    lines.append("tasks:")
    for row in inventory["tasks"]:
        session_id = row.get("session_id") or "none"
        artifacts = row.get("artifacts", {})
        lines.append(
            f"{row['task_id']}: status={row['status']} session_id={session_id} "
            f"iterations={row['iterations']} archived={row['archived']} "
            f"prompt={artifacts.get('prompt') or 'none'} "
            f"log={artifacts.get('log') or 'none'} "
            f"run={artifacts.get('run') or 'none'}"
        )
    return "\n".join(lines)


def build_evidence_bundle(
    project_dir: Path,
    *,
    task_id: str | None = None,
    latest: bool = False,
    prompt_lines: int = 20,
    log_lines: int = 20,
    event_limit: int = 10,
) -> dict[str, Any] | None:
    inventory = build_session_inventory(project_dir)
    selection = "current_task"
    if task_id is not None:
        selection = "task_id"
        session = next(
            (
                row
                for row in inventory.get("tasks", [])
                if row.get("task_id") == task_id
            ),
            None,
        )
    elif latest:
        selection = "latest_session"
        session = inventory.get("latest_session")
    else:
        current_task_id = inventory.get("current_task")
        session = next(
            (
                row
                for row in inventory.get("tasks", [])
                if row.get("task_id") == current_task_id
            ),
            None,
        )
    if session is None:
        return None
    selected_task_id = session.get("task_id")
    recent_events = (
        load_events_timeline(
            project_dir,
            limit=event_limit,
            task_id=str(selected_task_id) if selected_task_id else None,
        )
        if selected_task_id
        else []
    )
    recent_watchdog_events = _load_recent_watchdog_events(project_dir, limit=event_limit)
    artifacts = dict(session.get("artifacts", {}))
    return {
        "project_name": inventory.get("project_name"),
        "overall_status": inventory.get("overall_status"),
        "generated_at": _now(),
        "task_id": session.get("task_id"),
        "session_id": session.get("session_id"),
        "timestamp": session.get("timestamp") or session.get("updated_at"),
        "event_type": session.get("event_type"),
        "agent_status": session.get("agent_status") or session.get("status"),
        "summary": session.get("summary") or session.get("last_summary"),
        "selection": selection,
        "status_snapshot": build_status_snapshot(project_dir),
        "session_snapshot": dict(session),
        "artifacts": artifacts,
        "events_summary": summarize_events(recent_events),
        "recent_events": recent_events,
        "watchdog_events_summary": summarize_events(recent_watchdog_events),
        "recent_watchdog_events": recent_watchdog_events,
        "prompt_preview": _read_text_preview(
            artifacts.get("prompt"),
            lines=prompt_lines,
        ),
        "log_tail": _read_text_preview(
            artifacts.get("log"),
            lines=log_lines,
            from_end=True,
        ),
        "run_payload": _read_json_payload(artifacts.get("run")),
    }


def format_evidence_report(
    project_dir: Path,
    *,
    task_id: str | None = None,
    latest: bool = False,
    prompt_lines: int = 20,
    log_lines: int = 20,
    event_limit: int = 10,
) -> str:
    evidence = build_evidence_bundle(
        project_dir,
        task_id=task_id,
        latest=latest,
        prompt_lines=prompt_lines,
        log_lines=log_lines,
        event_limit=event_limit,
    )
    if evidence is None:
        return "No evidence recorded."
    lines = [
        f"project: {evidence.get('project_name')}",
        f"overall_status: {evidence.get('overall_status')}",
        f"task_id: {evidence.get('task_id')}",
        f"session_id: {evidence.get('session_id') or 'none'}",
        f"generated_at: {evidence.get('generated_at') or ''}",
        f"timestamp: {evidence.get('timestamp') or ''}",
        f"event_type: {evidence.get('event_type') or ''}",
        f"agent_status: {evidence.get('agent_status') or ''}",
        f"summary: {evidence.get('summary') or ''}",
        f"selection: {evidence.get('selection') or ''}",
        "artifacts:",
    ]
    for key in ("prompt", "log", "run"):
        lines.append(f"{key}: {evidence['artifacts'].get(key) or 'none'}")
    lines.append("prompt_preview:")
    lines.append(evidence.get("prompt_preview") or "")
    lines.append("log_tail:")
    lines.append(evidence.get("log_tail") or "")
    lines.append("status_snapshot:")
    lines.append(
        json.dumps(evidence.get("status_snapshot"), indent=2, ensure_ascii=False)
    )
    lines.append("session_snapshot:")
    lines.append(
        json.dumps(evidence.get("session_snapshot"), indent=2, ensure_ascii=False)
    )
    lines.append("events_summary:")
    lines.append(
        json.dumps(evidence.get("events_summary"), indent=2, ensure_ascii=False)
    )
    lines.append("recent_events:")
    lines.append(
        json.dumps(evidence.get("recent_events"), indent=2, ensure_ascii=False)
    )
    lines.append("watchdog_events_summary:")
    lines.append(
        json.dumps(evidence.get("watchdog_events_summary"), indent=2, ensure_ascii=False)
    )
    lines.append("recent_watchdog_events:")
    lines.append(
        json.dumps(evidence.get("recent_watchdog_events"), indent=2, ensure_ascii=False)
    )
    lines.append("run_payload:")
    lines.append(json.dumps(evidence.get("run_payload"), indent=2, ensure_ascii=False))
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
        "latest_watchdog_restart": None,
        "latest_watchdog_exhausted": None,
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
        if event_type in {"watchdog_restart", "watchdog_exhausted"}:
            field_name = f"latest_{event_type}"
            latest_watchdog_event = summary[field_name]
            if latest_watchdog_event is None or str(event.get("timestamp", "")) >= str(
                latest_watchdog_event.get("timestamp", "")
            ):
                summary[field_name] = {
                    "timestamp": event.get("timestamp"),
                    "summary": event.get("summary"),
                    "restart_reason": event.get("restart_reason"),
                    "restart_count": event.get("restart_count"),
                    "child_pid": event.get("child_pid"),
                    "child_exit_code": event.get("child_exit_code"),
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
    for field_name in ("latest_watchdog_restart", "latest_watchdog_exhausted"):
        lines.append(f"{field_name}:")
        payload = summary[field_name]
        if payload is not None:
            for key in (
                "timestamp",
                "summary",
                "restart_reason",
                "restart_count",
                "child_pid",
                "child_exit_code",
            ):
                value = payload.get(key)
                if value is not None:
                    lines.append(f"{key}: {value}")
    return "\n".join(lines)
