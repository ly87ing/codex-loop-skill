from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .cleanup import render_cleanup_report, run_cleanup
from .codex_runner import CodexRunner
from .config import CodexLoopConfig
from .doctor import render_doctor_report, run_doctor
from .hooks import HookRunner
from .init_flow import initialize_project
from .reporting import (
    build_evidence_bundle,
    build_session_inventory,
    format_evidence_report,
    format_events_summary,
    format_events_timeline,
    format_snapshots_report,
    format_snapshots_summary,
    format_sessions_report,
    format_status_summary,
    load_events_timeline,
    load_snapshots_index,
    summarize_snapshots,
    summarize_events,
    tail_log_lines,
)
from .run_flow import run_project
from .state_store import StateStore


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
    path.write_text(content, encoding="utf-8")


def _update_evidence_index(output_dir: Path, snapshot_path: Path, payload: dict[str, object] | None) -> None:
    index_path = output_dir.resolve() / "index.json"
    if index_path.exists():
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index_data = {"snapshots": []}
    snapshots = index_data.get("snapshots")
    if not isinstance(snapshots, list):
        snapshots = []
    status_snapshot = payload.get("status_snapshot") if isinstance(payload, dict) else {}
    if not isinstance(status_snapshot, dict):
        status_snapshot = {}
    snapshot_entry = {
        "generated_at": (payload or {}).get("generated_at"),
        "task_id": (payload or {}).get("task_id"),
        "selection": (payload or {}).get("selection"),
        "session_id": (payload or {}).get("session_id"),
        "overall_status": (payload or {}).get("overall_status"),
        "current_task": status_snapshot.get("current_task"),
        "last_blocker_code": status_snapshot.get("last_blocker_code"),
        "snapshot_path": str(snapshot_path.resolve()),
    }
    snapshots.append(snapshot_entry)
    index_data["snapshots"] = snapshots
    _write_output_file(index_path, json.dumps(index_data, indent=2, ensure_ascii=False))


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


def _load_optional_config(project_dir: Path) -> CodexLoopConfig | None:
    config_path = project_dir / "codex-loop.yaml"
    if not config_path.exists():
        return None
    return CodexLoopConfig.from_file(config_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Generate codex-loop files from a prompt.")
    init_parser.add_argument("--prompt", required=True, help="Project request to compile into files.")
    init_parser.add_argument(
        "--project-dir",
        default=".",
        help="Target project directory. Defaults to current directory.",
    )
    init_parser.add_argument("--model", default="gpt-5.4", help="Codex model to use.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing codex-loop files.")

    run_parser = subparsers.add_parser("run", help="Execute the autonomous loop.")
    run_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing codex-loop.yaml.",
    )

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
        "--summary",
        action="store_true",
        help="Render a grouped summary instead of the raw snapshot list.",
    )
    snapshots_parser.add_argument(
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
            return 0

        if args.command == "run":
            outcome = run_project(project_dir)
            print(outcome.value)
            return 0 if outcome.value == "completed" else 2

        if args.command == "status":
            if args.summary:
                print(format_status_summary(project_dir))
            else:
                state = StateStore(project_dir / ".codex-loop" / "state.json").load()
                print(json.dumps(state, indent=2, ensure_ascii=False))
            return 0

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
            snapshot_dir = Path(args.snapshot_dir).resolve()
            payload = load_snapshots_index(
                snapshot_dir,
                task_id=args.task_id,
                limit=args.limit,
                latest=args.latest,
            )
            if args.summary:
                summary = summarize_snapshots(payload)
                if args.json:
                    print(json.dumps(summary, indent=2, ensure_ascii=False))
                else:
                    print(format_snapshots_summary(payload))
                return 0
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    format_snapshots_report(
                        snapshot_dir,
                        task_id=args.task_id,
                        limit=args.limit,
                        latest=args.latest,
                    )
                )
            return 0

        if args.command == "doctor":
            report = run_doctor(project_dir, repair=args.repair)
            print(render_doctor_report(report))
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
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"codex-loop error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
