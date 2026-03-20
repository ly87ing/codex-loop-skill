from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from .cleanup import render_cleanup_report, run_cleanup
from .codex_runner import CodexRunner
from .config import CodexLoopConfig
from .daemon_manager import daemon_status, start_daemon, stop_daemon
from .doctor import render_doctor_report, run_doctor
from .hooks import HookRunner
from .init_flow import initialize_project
from .reporting import (
    build_evidence_bundle,
    build_health_snapshot,
    build_session_inventory,
    format_evidence_report,
    format_events_summary,
    format_events_timeline,
    format_health_report,
    format_snapshot_exports_report,
    format_snapshot_exports_summary,
    format_snapshots_report,
    format_snapshots_summary,
    format_sessions_report,
    format_status_summary,
    load_events_timeline,
    load_snapshot_exports_manifest,
    load_snapshots_index,
    summarize_snapshot_exports,
    summarize_snapshots,
    summarize_events,
    tail_log_lines,
)
from .run_flow import run_project, run_project_continuously, retry_blocked_tasks_for_retry
from .service_manager import install_service, service_status, uninstall_service
from .state_store import StateStore
from .watchdog_manager import run_watchdog


def _health_exit_code(health: str | None) -> int:
    if health == "error":
        return 3
    if health == "degraded":
        return 2
    return 0


def _collect_cleanup_overrides(args: argparse.Namespace) -> tuple[dict[str, int], dict[str, int]]:
    keep_overrides: dict[str, int] = {}
    age_overrides: dict[str, int] = {}
    for directory_name in ("logs", "runs", "prompts"):
        keep_value = getattr(args, f"{directory_name}_keep", None)
        if keep_value is not None:
            keep_overrides[directory_name] = keep_value
        age_value = getattr(args, f"{directory_name}_older_than_days", None)
        if age_value is not None:
            age_overrides[directory_name] = age_value
    return keep_overrides, age_overrides


def _write_output_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _update_evidence_index(output_dir: Path, snapshot_path: Path, payload: dict[str, object] | None) -> None:
    index_path = output_dir.resolve() / "index.json"
    if index_path.exists():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            index_data = {"snapshots": []}
    else:
        index_data = {"snapshots": []}
    snapshots = index_data.get("snapshots")
    if not isinstance(snapshots, list):
        snapshots = []
    status_snapshot = payload.get("status_snapshot") if isinstance(payload, dict) else {}
    if not isinstance(status_snapshot, dict):
        status_snapshot = {}
    watchdog_events_summary = (
        payload.get("watchdog_events_summary") if isinstance(payload, dict) else {}
    )
    if not isinstance(watchdog_events_summary, dict):
        watchdog_events_summary = {}
    latest_watchdog_exhausted = watchdog_events_summary.get("latest_watchdog_exhausted")
    if not isinstance(latest_watchdog_exhausted, dict):
        latest_watchdog_exhausted = {}
    snapshot_entry = {
        "generated_at": (payload or {}).get("generated_at"),
        "task_id": (payload or {}).get("task_id"),
        "selection": (payload or {}).get("selection"),
        "session_id": (payload or {}).get("session_id"),
        "overall_status": (payload or {}).get("overall_status"),
        "current_task": status_snapshot.get("current_task"),
        "last_blocker_code": status_snapshot.get("last_blocker_code"),
        "watchdog_phase": status_snapshot.get("watchdog_phase"),
        "watchdog_restart_count": status_snapshot.get("watchdog_restart_count"),
        "watchdog_last_restart_reason": status_snapshot.get(
            "watchdog_last_restart_reason"
        ),
        "latest_watchdog_exhausted_reason": latest_watchdog_exhausted.get(
            "restart_reason"
        ),
        "snapshot_path": str(snapshot_path.resolve()),
    }
    snapshots.append(snapshot_entry)
    index_data["snapshots"] = snapshots
    _write_output_file(index_path, json.dumps(index_data, indent=2, ensure_ascii=False))


def _update_snapshots_manifest(
    output_dir: Path,
    export_path: Path,
    *,
    source_snapshot_dir: Path,
    snapshot_count: int,
    summary: bool,
    group_by: str | None,
    json_output: bool,
    task_id: str | None,
    status: str | None,
    blocker_code: str | None,
    watchdog_phase: str | None,
    latest: bool,
    latest_blocked: bool,
    sort_order: str,
    since: str | None,
    until: str | None,
) -> None:
    manifest_path = output_dir.resolve() / "manifest.json"
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            manifest_data = {"exports": []}
    else:
        manifest_data = {"exports": []}
    exports = manifest_data.get("exports")
    if not isinstance(exports, list):
        exports = []
    exports.append(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "export_path": str(export_path.resolve()),
            "source_snapshot_dir": str(source_snapshot_dir.resolve()),
            "snapshot_count": snapshot_count,
            "summary": summary,
            "group_by": group_by,
            "render_format": "json" if json_output else "text",
            "filters": {
                "task_id": task_id,
                "status": status,
                "blocker_code": blocker_code,
                "watchdog_phase": watchdog_phase,
                "latest": latest,
                "latest_blocked": latest_blocked,
                "sort_order": sort_order,
                "since": since,
                "until": until,
            },
        }
    )
    manifest_data["exports"] = exports
    _write_output_file(manifest_path, json.dumps(manifest_data, indent=2, ensure_ascii=False))


def _slugify_file_component(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)
    return cleaned.strip("-_") or "snapshot"


def _evidence_output_path(
    output_dir: Path,
    payload: dict[str, object] | None,
    *,
    json_output: bool,
) -> Path:
    task_id = _slugify_file_component(str((payload or {}).get("task_id") or "task"))
    selection = _slugify_file_component(str((payload or {}).get("selection") or "snapshot"))
    generated_at = str((payload or {}).get("generated_at") or "generated")
    timestamp = _slugify_file_component(
        generated_at.replace(":", "-").replace("+", "-").replace(".", "-")
    )
    suffix = ".json" if json_output else ".txt"
    return output_dir.resolve() / f"evidence-{task_id}-{selection}-{timestamp}{suffix}"


def _snapshots_output_path(
    output_dir: Path,
    *,
    json_output: bool,
    summary: bool,
    group_by: str | None,
    latest: bool,
    latest_blocked: bool,
    status: str | None,
    blocker_code: str | None,
    watchdog_phase: str | None,
    sort_order: str,
) -> Path:
    parts = ["snapshots", "summary" if summary else "list"]
    if group_by:
        parts.append(group_by)
    if latest_blocked:
        parts.append("latest-blocked")
    elif latest:
        parts.append("latest")
    if status:
        parts.append(f"status-{_slugify_file_component(status)}")
    if blocker_code:
        parts.append(f"blocker-{_slugify_file_component(blocker_code)}")
    if watchdog_phase:
        parts.append(f"watchdog-{_slugify_file_component(watchdog_phase)}")
    if sort_order != "oldest":
        parts.append(f"sort-{_slugify_file_component(sort_order)}")
    timestamp = _slugify_file_component(
        datetime.now(UTC).isoformat().replace(":", "-").replace("+", "-").replace(".", "-")
    )
    parts.append(timestamp)
    suffix = ".json" if json_output else ".txt"
    return output_dir.resolve() / f"{'-'.join(parts)}{suffix}"


def _snapshots_exports_output_path(
    output_dir: Path,
    *,
    json_output: bool,
    summary: bool,
    group_by: str | None,
    latest: bool,
    task_id: str | None,
    status: str | None,
    blocker_code: str | None,
    watchdog_phase: str | None,
) -> Path:
    parts = ["snapshot-exports", "summary" if summary else "list"]
    if group_by:
        parts.append(group_by)
    if latest:
        parts.append("latest")
    if task_id:
        parts.append(f"task-{_slugify_file_component(task_id)}")
    if status:
        parts.append(f"status-{_slugify_file_component(status)}")
    if blocker_code:
        parts.append(f"blocker-{_slugify_file_component(blocker_code)}")
    if watchdog_phase:
        parts.append(f"watchdog-{_slugify_file_component(watchdog_phase)}")
    timestamp = _slugify_file_component(
        datetime.now(UTC).isoformat().replace(":", "-").replace("+", "-").replace(".", "-")
    )
    parts.append(timestamp)
    suffix = ".json" if json_output else ".txt"
    return output_dir.resolve() / f"{'-'.join(parts)}{suffix}"


def _update_snapshots_exports_index(
    output_dir: Path,
    export_path: Path,
    *,
    source_exports_dir: Path,
    export_count: int,
    summary: bool,
    group_by: str | None,
    json_output: bool,
    task_id: str | None,
    status: str | None,
    blocker_code: str | None,
    watchdog_phase: str | None,
    latest: bool,
    limit: int | None,
) -> None:
    index_path = output_dir.resolve() / "index.json"
    if index_path.exists():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            index_data = {"exports": []}
    else:
        index_data = {"exports": []}
    exports = index_data.get("exports")
    if not isinstance(exports, list):
        exports = []
    exports.append(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "export_path": str(export_path.resolve()),
            "source_exports_dir": str(source_exports_dir.resolve()),
            "export_count": export_count,
            "summary": summary,
            "group_by": group_by,
            "render_format": "json" if json_output else "text",
            "filters": {
                "task_id": task_id,
                "status": status,
                "blocker_code": blocker_code,
                "watchdog_phase": watchdog_phase,
                "latest": latest,
                "limit": limit,
            },
        }
    )
    index_data["exports"] = exports
    _write_output_file(index_path, json.dumps(index_data, indent=2, ensure_ascii=False))


def _load_optional_config(project_dir: Path) -> CodexLoopConfig | None:
    config_path = project_dir / "codex-loop.yaml"
    if not config_path.exists():
        return None
    return CodexLoopConfig.from_file(config_path)


_HIDDEN_SUBCOMMANDS = frozenset({"watchdog"})


class _CleanHelpParser(argparse.ArgumentParser):
    """ArgumentParser that scrubs internal subcommands from help output."""

    def format_help(self) -> str:
        import re
        text = super().format_help()
        for name in _HIDDEN_SUBCOMMANDS:
            # Remove from usage line: e.g. {a,watchdog,b} → {a,b}
            text = re.sub(rf",?{re.escape(name)},?", lambda m: "," if m.group().startswith(",") and m.group().endswith(",") else "", text)
            # Remove the named subcommand listing line
            text = re.sub(rf"^\s+{re.escape(name)}.*\n", "", text, flags=re.MULTILINE)
        # Remove any residual ==SUPPRESS== lines (argparse renders hidden subcommands this way)
        text = re.sub(r"^[^\S\n]*==SUPPRESS==.*\n", "", text, flags=re.MULTILINE)
        # Clean up any double commas left in usage
        text = re.sub(r"\{,", "{", text)
        text = re.sub(r",\}", "}", text)
        text = re.sub(r",,+", ",", text)
        return text


def _build_parser() -> argparse.ArgumentParser:
    parser = _CleanHelpParser(
        prog="codex-loop",
        description="Autonomous coding loop supervisor for Codex CLI.",
        epilog=(
            "Quick start:\n"
            "  codex-loop init --prompt \"your goal\"   # scaffold spec, plan, tasks\n"
            "  codex-loop run                          # run until done or blocked\n"
            "  codex-loop status --summary             # check what happened\n"
            "\n"
            "Full docs: https://github.com/ly87ing/codex-loop-skill"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Generate codex-loop files from a prompt.")
    init_parser.add_argument("--prompt", required=True, help="Describe what you want to build. codex-loop will generate spec, plan, and task files from this description.")
    init_parser.add_argument(
        "--project-dir",
        default=".",
        help="Target project directory. Defaults to current directory.",
    )
    init_parser.add_argument("--model", default="gpt-5.4", help="Codex model to use (e.g. gpt-5.4).")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing codex-loop files.")

    run_parser = subparsers.add_parser("run", help="Execute the autonomous loop.")
    run_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing codex-loop.yaml.",
    )
    run_parser.add_argument(
        "--continuous",
        action="store_true",
        help="Keep re-running the loop until completion or max cycle limit.",
    )
    run_parser.add_argument(
        "--retry-blocked",
        action="store_true",
        help="Requeue blocked tasks before running so transient blockers can be retried.",
    )
    run_parser.add_argument(
        "--cycle-sleep-seconds",
        type=float,
        default=60.0,
        help="Sleep duration between continuous run cycles.",
    )
    run_parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Optional maximum number of continuous run cycles before returning.",
    )
    run_parser.add_argument(
        "--heartbeat-path",
        default=None,
        help=argparse.SUPPRESS,
    )
    run_parser.add_argument(
        "--retry-errors",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    run_parser.add_argument(
        "--max-error-retries",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )

    watchdog_parser = subparsers.add_parser("watchdog", help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--project-dir", default=".")
    watchdog_parser.add_argument("--heartbeat-path", required=True, help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--watchdog-state-path", required=True, help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--retry-blocked", action="store_true", help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--cycle-sleep-seconds", type=float, default=60.0, help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--max-cycles", type=int, default=None, help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--stale-after-seconds", type=float, default=300.0, help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--poll-interval-seconds", type=float, default=5.0, help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--restart-backoff-seconds", type=float, default=5.0, help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--terminate-timeout-seconds", type=float, default=10.0, help=argparse.SUPPRESS)
    watchdog_parser.add_argument("--max-restarts", type=int, default=None, help=argparse.SUPPRESS)

    status_parser = subparsers.add_parser("status", help="Print local loop state.")
    status_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop/state.json.",
    )
    status_parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a concise human-readable summary instead of raw JSON.",
    )

    health_parser = subparsers.add_parser(
        "health",
        help="Print a consolidated local health view.",
    )
    health_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing codex-loop.yaml.",
    )
    health_parser.add_argument(
        "--events-limit",
        type=int,
        default=20,
        help="Maximum number of recent events to include in the health view.",
    )
    health_parser.add_argument(
        "--snapshot-dir",
        default=None,
        help="Optional snapshots directory override; defaults to ./snapshots under the project.",
    )
    health_parser.add_argument(
        "--exports-dir",
        default=None,
        help="Optional snapshot exports directory override; defaults to ./snapshot-reports under the project.",
    )
    health_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )

    sessions_parser = subparsers.add_parser(
        "sessions",
        help="Inspect persisted Codex sessions for this workspace.",
    )
    sessions_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop/state.json.",
    )
    sessions_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )
    sessions_parser.add_argument(
        "--latest",
        action="store_true",
        help="Only emit the latest known session payload.",
    )
    sessions_parser.add_argument(
        "--task-id",
        default=None,
        help="Optional task id filter, for example 001-foundation.",
    )

    evidence_parser = subparsers.add_parser(
        "evidence",
        help="Render the latest operator evidence bundle for a task or session.",
    )
    evidence_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop/state.json.",
    )
    evidence_parser.add_argument(
        "--task-id",
        default=None,
        help="Optional task id filter, for example 001-foundation.",
    )
    evidence_parser.add_argument(
        "--latest",
        action="store_true",
        help="Use the latest known session instead of the current task.",
    )
    evidence_parser.add_argument(
        "--prompt-lines",
        type=int,
        default=20,
        help="Number of prompt preview lines to include.",
    )
    evidence_parser.add_argument(
        "--log-lines",
        type=int,
        default=20,
        help="Number of log tail lines to include.",
    )
    evidence_parser.add_argument(
        "--event-limit",
        type=int,
        default=10,
        help="Number of recent task events to include in the evidence bundle.",
    )
    evidence_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )
    evidence_parser.add_argument(
        "--output",
        default=None,
        help="Optional file path to write the rendered evidence payload.",
    )
    evidence_parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional directory for an auto-named evidence snapshot file.",
    )

    snapshots_parser = subparsers.add_parser(
        "snapshots",
        help="Inspect exported evidence snapshots from an index directory.",
    )
    snapshots_parser.add_argument(
        "--snapshot-dir",
        default="./snapshots",
        help="Directory containing evidence snapshot index.json.",
    )
    snapshots_parser.add_argument(
        "--task-id",
        default=None,
        help="Optional task id filter, for example 001-foundation.",
    )
    snapshots_parser.add_argument(
        "--status",
        default=None,
        help="Optional snapshot status filter, for example blocked or completed.",
    )
    snapshots_parser.add_argument(
        "--blocker-code",
        default=None,
        help="Optional blocker code filter, for example no_progress_limit.",
    )
    snapshots_parser.add_argument(
        "--watchdog-phase",
        default=None,
        help="Optional watchdog phase filter, for example exhausted or restarting.",
    )
    snapshots_parser.add_argument(
        "--sort",
        choices=("oldest", "newest"),
        default="oldest",
        help="Optional snapshot output order.",
    )
    snapshots_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of snapshots to print.",
    )
    snapshots_parser.add_argument(
        "--latest",
        action="store_true",
        help="Only emit the latest snapshot entry.",
    )
    snapshots_parser.add_argument(
        "--latest-blocked",
        action="store_true",
        help="Only emit the most recent blocked snapshot entry.",
    )
    snapshots_parser.add_argument(
        "--summary",
        action="store_true",
        help="Render a grouped summary instead of the raw snapshot list.",
    )
    snapshots_parser.add_argument(
        "--group-by",
        choices=("task", "status", "blocker", "selection"),
        default=None,
        help="Optional summary grouping dimension; only valid with --summary.",
    )
    snapshots_parser.add_argument(
        "--since",
        default=None,
        help="Optional lower inclusive ISO timestamp bound for generated_at.",
    )
    snapshots_parser.add_argument(
        "--until",
        default=None,
        help="Optional upper inclusive ISO timestamp bound for generated_at.",
    )
    snapshots_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )
    snapshots_parser.add_argument(
        "--output",
        default=None,
        help="Optional file path to write the rendered snapshots payload.",
    )
    snapshots_parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional directory for an auto-named snapshots export file.",
    )

    snapshots_exports_parser = subparsers.add_parser(
        "snapshots-exports",
        help="Inspect archived snapshots query exports from manifest.json.",
    )
    snapshots_exports_parser.add_argument(
        "--exports-dir",
        default="./snapshot-reports",
        help="Directory containing snapshots query manifest.json.",
    )
    snapshots_exports_parser.add_argument(
        "--latest",
        action="store_true",
        help="Only emit the latest archived export entry.",
    )
    snapshots_exports_parser.add_argument(
        "--task-id",
        default=None,
        help="Optional archived export task filter, for example 001-foundation.",
    )
    snapshots_exports_parser.add_argument(
        "--status",
        default=None,
        help="Optional archived export status filter, for example blocked.",
    )
    snapshots_exports_parser.add_argument(
        "--blocker-code",
        default=None,
        help="Optional archived export blocker code filter, for example no_progress_limit.",
    )
    snapshots_exports_parser.add_argument(
        "--watchdog-phase",
        default=None,
        help="Optional archived export watchdog phase filter, for example exhausted.",
    )
    snapshots_exports_parser.add_argument(
        "--summary",
        action="store_true",
        help="Render a grouped summary instead of the raw export list.",
    )
    snapshots_exports_parser.add_argument(
        "--group-by",
        choices=("task", "status", "blocker", "render", "summary"),
        default=None,
        help="Optional summary grouping dimension; only valid with --summary.",
    )
    snapshots_exports_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of archived exports to print.",
    )
    snapshots_exports_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )
    snapshots_exports_parser.add_argument(
        "--output",
        default=None,
        help="Optional file path to write the rendered snapshot exports payload.",
    )
    snapshots_exports_parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional directory for an auto-named snapshot exports file.",
    )

    daemon_parser = subparsers.add_parser("daemon", help="Manage a background codex-loop worker.")
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command", required=True)

    daemon_start_parser = daemon_subparsers.add_parser("start", help="Start a background worker.")
    daemon_start_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing codex-loop.yaml.",
    )
    daemon_start_parser.add_argument(
        "--retry-blocked",
        action="store_true",
        help="Requeue blocked tasks between cycles in the background worker.",
    )
    daemon_start_parser.add_argument(
        "--cycle-sleep-seconds",
        type=float,
        default=60.0,
        help="Sleep duration between continuous run cycles.",
    )
    daemon_start_parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Optional maximum number of continuous run cycles before returning.",
    )
    daemon_start_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )

    daemon_status_parser = daemon_subparsers.add_parser("status", help="Show daemon status.")
    daemon_status_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop.",
    )
    daemon_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )

    daemon_stop_parser = daemon_subparsers.add_parser("stop", help="Stop the daemon worker.")
    daemon_stop_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop.",
    )
    daemon_stop_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )
    daemon_restart_parser = daemon_subparsers.add_parser("restart", help="Restart the daemon worker.")
    daemon_restart_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop.",
    )
    daemon_restart_parser.add_argument(
        "--retry-blocked",
        action="store_true",
        help="Requeue blocked tasks between cycles in the background worker.",
    )
    daemon_restart_parser.add_argument(
        "--cycle-sleep-seconds",
        type=float,
        default=60.0,
        help="Sleep duration between continuous run cycles.",
    )
    daemon_restart_parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Optional maximum number of continuous run cycles before returning.",
    )
    daemon_restart_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )

    service_parser = subparsers.add_parser(
        "service",
        help="Manage a launchd-backed macOS service for codex-loop.",
    )
    service_subparsers = service_parser.add_subparsers(dest="service_command", required=True)

    service_install_parser = service_subparsers.add_parser(
        "install",
        help="Install or refresh a launchd service.",
    )
    service_install_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing codex-loop.yaml.",
    )
    service_install_parser.add_argument(
        "--retry-blocked",
        action="store_true",
        help="Requeue blocked tasks between continuous cycles.",
    )
    service_install_parser.add_argument(
        "--cycle-sleep-seconds",
        type=float,
        default=60.0,
        help="Sleep duration between continuous run cycles.",
    )
    service_install_parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Optional maximum number of continuous run cycles before returning.",
    )
    service_install_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )

    service_status_parser = service_subparsers.add_parser(
        "status",
        help="Show launchd service status.",
    )
    service_status_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop.",
    )
    service_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )

    service_uninstall_parser = service_subparsers.add_parser(
        "uninstall",
        help="Remove the launchd service.",
    )
    service_uninstall_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop.",
    )
    service_uninstall_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )
    service_reinstall_parser = service_subparsers.add_parser(
        "reinstall",
        help="Reinstall or refresh the launchd service.",
    )
    service_reinstall_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing codex-loop.yaml.",
    )
    service_reinstall_parser.add_argument(
        "--retry-blocked",
        action="store_true",
        help="Requeue blocked tasks between continuous cycles.",
    )
    service_reinstall_parser.add_argument(
        "--cycle-sleep-seconds",
        type=float,
        default=60.0,
        help="Sleep duration between continuous run cycles.",
    )
    service_reinstall_parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Optional maximum number of continuous run cycles before returning.",
    )
    service_reinstall_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Validate local loop files.")
    doctor_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing codex-loop.yaml.",
    )
    doctor_parser.add_argument(
        "--repair",
        action="store_true",
        help="Repair schema/state/task drift where possible.",
    )

    events_parser = subparsers.add_parser("events", help="Render a concise loop timeline.")
    events_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop/state.json.",
    )
    events_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of timeline entries to print.",
    )
    events_parser.add_argument(
        "--task-id",
        default=None,
        help="Optional task id filter, for example 001-foundation.",
    )
    events_parser.add_argument(
        "--event-type",
        default=None,
        help="Optional event label filter, for example iteration:continue or hook:post_iteration.",
    )
    events_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of formatted text.",
    )
    events_parser.add_argument(
        "--since",
        default=None,
        help="Optional lower inclusive ISO timestamp bound.",
    )
    events_parser.add_argument(
        "--until",
        default=None,
        help="Optional upper inclusive ISO timestamp bound.",
    )
    events_parser.add_argument(
        "--output",
        default=None,
        help="Optional file path to write the rendered events payload.",
    )
    events_parser.add_argument(
        "--summary",
        action="store_true",
        help="Aggregate the filtered events instead of printing the full timeline.",
    )

    cleanup_parser = subparsers.add_parser("cleanup", help="Prune old local loop artifacts.")
    cleanup_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop state.",
    )
    cleanup_parser.add_argument(
        "--keep",
        type=int,
        default=None,
        help="Number of most recent files to keep in each artifact directory.",
    )
    cleanup_parser.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help="Only remove artifacts or stale worktrees older than this many days.",
    )
    cleanup_parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete files instead of running in dry-run mode.",
    )
    cleanup_parser.add_argument(
        "--no-worktrees",
        action="store_true",
        help="Do not remove stale .codex-loop worktrees.",
    )
    cleanup_parser.add_argument("--logs-keep", type=int, default=None, help="Override keep count for logs.")
    cleanup_parser.add_argument("--runs-keep", type=int, default=None, help="Override keep count for runs.")
    cleanup_parser.add_argument(
        "--prompts-keep",
        type=int,
        default=None,
        help="Override keep count for prompts.",
    )
    cleanup_parser.add_argument(
        "--logs-older-than-days",
        type=int,
        default=None,
        help="Override age threshold for logs.",
    )
    cleanup_parser.add_argument(
        "--runs-older-than-days",
        type=int,
        default=None,
        help="Override age threshold for runs.",
    )
    cleanup_parser.add_argument(
        "--prompts-older-than-days",
        type=int,
        default=None,
        help="Override age threshold for prompts.",
    )

    logs_parser = subparsers.add_parser("logs", help="Inspect persisted loop logs.")
    logs_subparsers = logs_parser.add_subparsers(dest="logs_command", required=True)
    tail_parser = logs_subparsers.add_parser("tail", help="Print the latest saved JSONL log.")
    tail_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop/logs.",
    )
    tail_parser.add_argument(
        "--lines",
        type=int,
        default=40,
        help="Number of lines to print from the end of the latest log.",
    )
    tail_parser.add_argument(
        "--task-id",
        default=None,
        help="Optional task id filter, for example 001-foundation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_dir = Path(getattr(args, "project_dir", ".")).resolve()

    try:
        if args.command == "init":
            print("Generating spec, plan, and tasks from your prompt...", flush=True)
            print("(This calls Codex to produce your project files — usually takes 30–90 seconds.)", flush=True)
            runner = CodexRunner(project_dir)
            result = runner.initialize_from_prompt(prompt=args.prompt, model=args.model)
            initialize_project(
                project_dir=project_dir,
                prompt=args.prompt,
                result=result,
                force=args.force,
            )
            config = CodexLoopConfig.from_file(project_dir / "codex-loop.yaml")
            hook_runner = HookRunner(project_dir / ".codex-loop" / "hooks")
            hook_results = hook_runner.run(
                event_name="post_init",
                commands=config.hooks.post_init,
                cwd=project_dir,
                env={"CODEX_LOOP_PROJECT_DIR": str(project_dir)},
                timeout_seconds=config.hooks.timeout_seconds,
            )
            if config.hooks.failure_policy == "block":
                failure = hook_runner.first_failure(hook_results)
                reason = hook_runner.failure_reason("post_init", failure)
                if reason is not None:
                    raise RuntimeError(reason)
            print(f"Initialized codex-loop files in {project_dir}")
            print()
            print("Next steps:")
            print(f"  1. Open {project_dir / 'codex-loop.yaml'} — check that verification.commands")
            print( "     matches how you run your tests. For example:")
            print( "       Python:  \"python -m pytest tests/ -q\"")
            print( "       Node:    \"npm test\"")
            print( "       Go:      \"go test ./...\"")
            print(f"  2. Skim {project_dir / 'tasks'} to make sure the tasks look right.")
            print( "     If the tasks don't match your goal, re-run: codex-loop init --prompt \"...\" --force")
            print(f"  3. Make sure this directory is a Git repo with at least one commit:")
            print( "       git init && git add . && git commit -m 'init'  (skip if you already have commits)")
            print(f"  4. If you haven't already, trust this directory in Codex: run 'codex' once inside it and accept the prompt.")
            print(f"  5. Run:  codex-loop run")
            return 0

        if args.command == "run":
            if not (project_dir / "codex-loop.yaml").exists():
                print(
                    f"codex-loop error: no codex-loop.yaml found in {project_dir}\n"
                    "Run 'codex-loop init --prompt \"your goal\"' first to set up the project.",
                    file=sys.stderr,
                )
                return 1
            if args.max_cycles is not None and not args.continuous:
                raise ValueError("Use --max-cycles only with --continuous.")
            if args.cycle_sleep_seconds < 0:
                raise ValueError("--cycle-sleep-seconds must not be negative.")
            if args.max_cycles is not None and args.max_cycles <= 0:
                raise ValueError("--max-cycles must be greater than zero.")
            if args.continuous:
                continuous_kwargs = {
                    "retry_blocked": args.retry_blocked,
                    "cycle_sleep_seconds": args.cycle_sleep_seconds,
                    "max_cycles": args.max_cycles,
                }
                if args.retry_errors:
                    continuous_kwargs["retry_errors"] = True
                if args.max_error_retries is not None:
                    continuous_kwargs["max_error_retries"] = args.max_error_retries
                heartbeat_path = (
                    Path(args.heartbeat_path).resolve()
                    if args.heartbeat_path
                    else (
                        Path(os.environ["CODEX_LOOP_HEARTBEAT_PATH"]).resolve()
                        if os.environ.get("CODEX_LOOP_HEARTBEAT_PATH")
                        else None
                    )
                )
                if heartbeat_path is not None:
                    continuous_kwargs["heartbeat_path"] = heartbeat_path
                print("Starting codex-loop run (continuous mode)...", flush=True)
                outcome = run_project_continuously(
                    project_dir,
                    **continuous_kwargs,
                )
            else:
                if args.retry_blocked:
                    retry_blocked_tasks_for_retry(project_dir)
                print("Starting codex-loop run...", flush=True)
                outcome = run_project(project_dir)
            print(outcome.value)
            try:
                _state = StateStore(project_dir / ".codex-loop" / "state.json").load()
                if outcome.value == "completed":
                    _branch = _state.get("meta", {}).get("worktree_branch")
                    if _branch:
                        print(f"Changes are on branch: {_branch}")
                        print(f"To merge: git merge {_branch}")
                        print("After merging, clean up with: codex-loop cleanup --apply")
                else:
                    _blocker = _state.get("meta", {}).get("last_blocker") or {}
                    if _blocker.get("reason"):
                        print(
                            f"Blocked: [{_blocker.get('code', '?')}] {_blocker['reason']}",
                            file=sys.stderr,
                        )
                    print("Run 'codex-loop status --summary' for full details.", file=sys.stderr)
                    print("To retry: codex-loop run --retry-blocked", file=sys.stderr)
            except Exception:  # noqa: BLE001
                pass
            return 0 if outcome.value == "completed" else 2

        if args.command == "watchdog":
            if args.cycle_sleep_seconds < 0:
                raise ValueError("--cycle-sleep-seconds must not be negative.")
            if args.max_cycles is not None and args.max_cycles <= 0:
                raise ValueError("--max-cycles must be greater than zero.")
            if args.stale_after_seconds <= 0:
                raise ValueError("--stale-after-seconds must be greater than zero.")
            if args.poll_interval_seconds < 0:
                raise ValueError("--poll-interval-seconds must not be negative.")
            if args.restart_backoff_seconds < 0:
                raise ValueError("--restart-backoff-seconds must not be negative.")
            if args.terminate_timeout_seconds <= 0:
                raise ValueError("--terminate-timeout-seconds must be greater than zero.")
            if args.max_restarts is not None and args.max_restarts < 0:
                raise ValueError("--max-restarts must not be negative.")
            return run_watchdog(
                project_dir,
                heartbeat_path=Path(args.heartbeat_path).resolve(),
                watchdog_state_path=Path(args.watchdog_state_path).resolve(),
                retry_blocked=args.retry_blocked,
                cycle_sleep_seconds=args.cycle_sleep_seconds,
                max_cycles=args.max_cycles,
                stale_after_seconds=args.stale_after_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                restart_backoff_seconds=args.restart_backoff_seconds,
                terminate_timeout_seconds=args.terminate_timeout_seconds,
                max_restarts=args.max_restarts,
            )

        if args.command == "daemon" and args.daemon_command == "start":
            if args.cycle_sleep_seconds < 0:
                raise ValueError("--cycle-sleep-seconds must not be negative.")
            if args.max_cycles is not None and args.max_cycles <= 0:
                raise ValueError("--max-cycles must be greater than zero.")
            payload = start_daemon(
                project_dir,
                retry_blocked=args.retry_blocked,
                cycle_sleep_seconds=args.cycle_sleep_seconds,
                max_cycles=args.max_cycles,
            )
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    f"Started daemon pid={payload['pid']} log={payload['log_path']}"
                )
            return 0

        if args.command == "daemon" and args.daemon_command == "status":
            payload = daemon_status(project_dir)
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    f"running={payload.get('running')} "
                    f"dead_process={payload.get('dead_process')} "
                    f"stale_heartbeat={payload.get('stale_heartbeat')} "
                    f"pid={payload.get('pid')} "
                    f"max_restarts={payload.get('max_restarts')} "
                    f"restart_backoff_seconds={payload.get('restart_backoff_seconds')} "
                    f"restart_count={payload.get('restart_count')} "
                    f"last_restart_reason={payload.get('last_restart_reason')} "
                    f"phase={payload.get('phase')} "
                    f"cycle={payload.get('cycle')} "
                    f"error_count={payload.get('error_count')} "
                    f"log={payload.get('log_path')}"
                )
            return 0

        if args.command == "daemon" and args.daemon_command == "stop":
            payload = stop_daemon(project_dir)
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    f"Stopped daemon pid={payload['pid']} signal={payload['signal']}"
                )
            return 0

        if args.command == "daemon" and args.daemon_command == "restart":
            if args.cycle_sleep_seconds < 0:
                raise ValueError("--cycle-sleep-seconds must not be negative.")
            if args.max_cycles is not None and args.max_cycles <= 0:
                raise ValueError("--max-cycles must be greater than zero.")
            stop_daemon(project_dir)
            payload = start_daemon(
                project_dir,
                retry_blocked=args.retry_blocked,
                cycle_sleep_seconds=args.cycle_sleep_seconds,
                max_cycles=args.max_cycles,
            )
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    f"Restarted daemon pid={payload['pid']} log={payload['log_path']}"
                )
            return 0

        if args.command == "service" and args.service_command == "install":
            if args.cycle_sleep_seconds < 0:
                raise ValueError("--cycle-sleep-seconds must not be negative.")
            if args.max_cycles is not None and args.max_cycles <= 0:
                raise ValueError("--max-cycles must be greater than zero.")
            payload = install_service(
                project_dir,
                retry_blocked=args.retry_blocked,
                cycle_sleep_seconds=args.cycle_sleep_seconds,
                max_cycles=args.max_cycles,
            )
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    f"Installed service label={payload['label']} plist={payload['plist_path']}"
                )
            return 0

        if args.command == "service" and args.service_command == "status":
            payload = service_status(project_dir)
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    f"installed={payload.get('installed')} "
                    f"loaded={payload.get('loaded')} "
                    f"healthy={payload.get('healthy')} "
                    f"stale_heartbeat={payload.get('stale_heartbeat')} "
                    f"missing_heartbeat={payload.get('missing_heartbeat')} "
                    f"max_restarts={payload.get('max_restarts')} "
                    f"restart_backoff_seconds={payload.get('restart_backoff_seconds')} "
                    f"restart_count={payload.get('restart_count')} "
                    f"last_restart_reason={payload.get('last_restart_reason')} "
                    f"label={payload.get('label')} "
                    f"phase={payload.get('phase')} "
                    f"cycle={payload.get('cycle')} "
                    f"log={payload.get('log_path')}"
                )
            return 0

        if args.command == "service" and args.service_command == "uninstall":
            payload = uninstall_service(project_dir)
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    f"Removed service label={payload['label']} plist={payload['plist_path']}"
                )
            return 0

        if args.command == "service" and args.service_command == "reinstall":
            if args.cycle_sleep_seconds < 0:
                raise ValueError("--cycle-sleep-seconds must not be negative.")
            if args.max_cycles is not None and args.max_cycles <= 0:
                raise ValueError("--max-cycles must be greater than zero.")
            payload = install_service(
                project_dir,
                retry_blocked=args.retry_blocked,
                cycle_sleep_seconds=args.cycle_sleep_seconds,
                max_cycles=args.max_cycles,
            )
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    f"Reinstalled service label={payload['label']} plist={payload['plist_path']}"
                )
            return 0

        if args.command == "status":
            if not (project_dir / ".codex-loop" / "state.json").exists():
                print(
                    f"codex-loop error: no state found in {project_dir}\n"
                    "Run 'codex-loop init --prompt \"your goal\"' first, then 'codex-loop run'.",
                    file=sys.stderr,
                )
                return 1
            if args.summary:
                print(format_status_summary(project_dir))
            else:
                state = StateStore(project_dir / ".codex-loop" / "state.json").load()
                print(json.dumps(state, indent=2, ensure_ascii=False))
            return 0

        if args.command == "health":
            snapshot_dir = Path(args.snapshot_dir).resolve() if args.snapshot_dir else None
            exports_dir = Path(args.exports_dir).resolve() if args.exports_dir else None
            payload = build_health_snapshot(
                project_dir,
                events_limit=args.events_limit,
                snapshot_dir=snapshot_dir,
                exports_dir=exports_dir,
            )
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    format_health_report(
                        project_dir,
                        events_limit=args.events_limit,
                        snapshot_dir=snapshot_dir,
                        exports_dir=exports_dir,
                    )
                )
                if not (project_dir / "codex-loop.yaml").exists():
                    print("Hint: run 'codex-loop init --prompt \"your goal\"' first to set up the project.")
            return _health_exit_code(str(payload.get("health")))

        if args.command == "sessions":
            inventory = build_session_inventory(project_dir)
            if args.task_id is not None:
                payload = next(
                    (
                        row
                        for row in inventory.get("tasks", [])
                        if row.get("task_id") == args.task_id
                    ),
                    None,
                )
                if payload is None:
                    raise ValueError(f"Unknown task id for sessions view: {args.task_id}")
            else:
                payload = inventory.get("latest_session") if args.latest else inventory
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                if args.task_id is not None:
                    print(json.dumps(payload, indent=2, ensure_ascii=False))
                elif args.latest:
                    if payload is None:
                        print("No sessions recorded.")
                    else:
                        print(json.dumps(payload, indent=2, ensure_ascii=False))
                else:
                    print(format_sessions_report(project_dir))
            return 0

        if args.command == "evidence":
            if args.output and args.output_dir:
                raise ValueError("Use either --output or --output-dir for evidence, not both.")
            payload = build_evidence_bundle(
                project_dir,
                task_id=args.task_id,
                latest=args.latest,
                prompt_lines=args.prompt_lines,
                log_lines=args.log_lines,
                event_limit=args.event_limit,
            )
            if args.json:
                rendered = json.dumps(payload, indent=2, ensure_ascii=False)
            else:
                rendered = format_evidence_report(
                    project_dir,
                    task_id=args.task_id,
                    latest=args.latest,
                    prompt_lines=args.prompt_lines,
                    log_lines=args.log_lines,
                    event_limit=args.event_limit,
                )
            if args.output:
                output_path = Path(args.output).resolve()
                _write_output_file(output_path, rendered)
                print(f"Wrote evidence to {output_path}")
            elif args.output_dir:
                output_path = _evidence_output_path(
                    Path(args.output_dir),
                    payload,
                    json_output=bool(args.json),
                )
                _write_output_file(output_path, rendered)
                _update_evidence_index(output_path.parent, output_path, payload)
                print(f"Wrote evidence to {output_path}")
            else:
                print(rendered)
            return 0

        if args.command == "snapshots":
            if args.latest and args.latest_blocked:
                raise ValueError("Use either --latest or --latest-blocked, not both.")
            if args.group_by and not args.summary:
                raise ValueError("Use --group-by only with --summary.")
            if args.output and args.output_dir:
                raise ValueError("Use either --output or --output-dir for snapshots, not both.")
            snapshot_dir = Path(args.snapshot_dir).resolve()
            payload = load_snapshots_index(
                snapshot_dir,
                task_id=args.task_id,
                status=args.status,
                blocker_code=args.blocker_code,
                watchdog_phase=args.watchdog_phase,
                since=args.since,
                until=args.until,
                sort_order=args.sort,
                limit=args.limit,
                latest=args.latest,
                latest_blocked=args.latest_blocked,
            )
            if args.summary:
                summary = summarize_snapshots(payload, group_by=args.group_by)
                if args.json:
                    rendered = json.dumps(summary, indent=2, ensure_ascii=False)
                else:
                    rendered = format_snapshots_summary(payload, group_by=args.group_by)
            else:
                if args.json:
                    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
                else:
                    rendered = format_snapshots_report(
                        snapshot_dir,
                        task_id=args.task_id,
                        status=args.status,
                        blocker_code=args.blocker_code,
                        watchdog_phase=args.watchdog_phase,
                        since=args.since,
                        until=args.until,
                        sort_order=args.sort,
                        limit=args.limit,
                        latest=args.latest,
                        latest_blocked=args.latest_blocked,
                    )
            if args.output:
                output_path = Path(args.output).resolve()
                _write_output_file(output_path, rendered)
                print(f"Wrote snapshots to {output_path}")
            elif args.output_dir:
                output_path = _snapshots_output_path(
                    Path(args.output_dir),
                    json_output=bool(args.json),
                    summary=bool(args.summary),
                    group_by=args.group_by,
                    latest=bool(args.latest),
                    latest_blocked=bool(args.latest_blocked),
                    status=args.status,
                    blocker_code=args.blocker_code,
                    watchdog_phase=args.watchdog_phase,
                    sort_order=args.sort,
                )
                _write_output_file(output_path, rendered)
                _update_snapshots_manifest(
                    output_path.parent,
                    output_path,
                    source_snapshot_dir=snapshot_dir,
                    snapshot_count=len(payload),
                    summary=bool(args.summary),
                    group_by=args.group_by,
                    json_output=bool(args.json),
                    task_id=args.task_id,
                    status=args.status,
                    blocker_code=args.blocker_code,
                    watchdog_phase=args.watchdog_phase,
                    latest=bool(args.latest),
                    latest_blocked=bool(args.latest_blocked),
                    sort_order=args.sort,
                    since=args.since,
                    until=args.until,
                )
                print(f"Wrote snapshots to {output_path}")
            else:
                print(rendered)
            return 0

        if args.command == "doctor":
            report = run_doctor(project_dir, repair=args.repair)
            print(render_doctor_report(report))
            return 0

        if args.command == "snapshots-exports":
            if args.group_by is not None and not args.summary:
                raise ValueError("Use --group-by only with --summary.")
            if args.output and args.output_dir:
                raise ValueError(
                    "Use either --output or --output-dir for snapshot exports, not both."
                )
            exports_dir = Path(args.exports_dir).resolve()
            payload = load_snapshot_exports_manifest(
                exports_dir,
                task_id=args.task_id,
                status=args.status,
                blocker_code=args.blocker_code,
                watchdog_phase=args.watchdog_phase,
                latest=args.latest,
                limit=args.limit,
            )
            if args.summary:
                summary = summarize_snapshot_exports(payload, group_by=args.group_by)
                if args.json:
                    rendered = json.dumps(summary, indent=2, ensure_ascii=False)
                else:
                    rendered = format_snapshot_exports_summary(
                        payload,
                        group_by=args.group_by,
                    )
            else:
                if args.json:
                    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
                else:
                    rendered = format_snapshot_exports_report(
                        exports_dir,
                        task_id=args.task_id,
                        status=args.status,
                        blocker_code=args.blocker_code,
                        watchdog_phase=args.watchdog_phase,
                        latest=args.latest,
                        limit=args.limit,
                    )
            if args.output:
                output_path = Path(args.output).resolve()
                _write_output_file(output_path, rendered)
                print(f"Wrote snapshot exports to {output_path}")
            elif args.output_dir:
                output_path = _snapshots_exports_output_path(
                    Path(args.output_dir),
                    json_output=bool(args.json),
                    summary=bool(args.summary),
                    group_by=args.group_by,
                    latest=bool(args.latest),
                    task_id=args.task_id,
                    status=args.status,
                    blocker_code=args.blocker_code,
                    watchdog_phase=args.watchdog_phase,
                )
                _write_output_file(output_path, rendered)
                _update_snapshots_exports_index(
                    output_path.parent,
                    output_path,
                    source_exports_dir=exports_dir,
                    export_count=len(payload),
                    summary=bool(args.summary),
                    group_by=args.group_by,
                    json_output=bool(args.json),
                    task_id=args.task_id,
                    status=args.status,
                    blocker_code=args.blocker_code,
                    watchdog_phase=args.watchdog_phase,
                    latest=bool(args.latest),
                    limit=args.limit,
                )
                print(f"Wrote snapshot exports to {output_path}")
            else:
                print(rendered)
            return 0

        if args.command == "events":
            config = _load_optional_config(project_dir)
            limit = (
                args.limit
                if args.limit is not None
                else (
                    config.operator.events.default_limit
                    if config is not None
                    else 20
                )
            )
            events = load_events_timeline(
                project_dir,
                limit=limit,
                task_id=args.task_id,
                event_type=args.event_type,
                since=args.since,
                until=args.until,
            )
            if args.json:
                payload = summarize_events(events) if args.summary else events
                rendered = json.dumps(payload, indent=2, ensure_ascii=False)
            else:
                rendered = (
                    format_events_summary(events)
                    if args.summary
                    else format_events_timeline(
                        project_dir,
                        limit=limit,
                        task_id=args.task_id,
                        event_type=args.event_type,
                        since=args.since,
                        until=args.until,
                    )
                )
            if args.output:
                output_path = Path(args.output).resolve()
                _write_output_file(output_path, rendered)
                print(f"Wrote events to {output_path}")
            else:
                print(rendered)
            return 0

        if args.command == "cleanup":
            config = _load_optional_config(project_dir)
            keep_overrides, age_overrides = _collect_cleanup_overrides(args)
            default_keep = (
                args.keep
                if args.keep is not None
                else (
                    config.operator.cleanup.keep
                    if config is not None
                    else 10
                )
            )
            default_age = (
                args.older_than_days
                if args.older_than_days is not None
                else (
                    config.operator.cleanup.older_than_days
                    if config is not None
                    else None
                )
            )
            merged_keep = (
                dict(config.operator.cleanup.directory_keep) if config is not None else {}
            )
            merged_keep.update(keep_overrides)
            merged_age = (
                dict(config.operator.cleanup.directory_older_than_days)
                if config is not None
                else {}
            )
            merged_age.update(age_overrides)
            cleanup_kwargs = {
                "apply": args.apply,
                "keep": default_keep,
                "older_than_days": default_age,
                "remove_worktrees": not args.no_worktrees,
            }
            if merged_keep:
                cleanup_kwargs["directory_keep"] = merged_keep
            if merged_age:
                cleanup_kwargs["directory_older_than_days"] = merged_age
            print(
                render_cleanup_report(
                    run_cleanup(
                        project_dir,
                        **cleanup_kwargs,
                    )
                )
            )
            return 0

        if args.command == "logs" and args.logs_command == "tail":
            print(
                tail_log_lines(
                    project_dir,
                    lines=args.lines,
                    task_id=args.task_id,
                )
            )
            return 0
    except (OSError, RuntimeError, ValueError, TypeError, subprocess.CalledProcessError) as exc:
        msg = str(exc)
        print(f"codex-loop error: {msg}", file=sys.stderr)
        if "state.json" in msg and "No state file found" in msg:
            print("Run 'codex-loop init --prompt \"your goal\"' first, then 'codex-loop run'.", file=sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
