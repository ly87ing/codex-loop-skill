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
    format_events_timeline,
    format_status_summary,
    load_events_timeline,
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
        default=20,
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

    cleanup_parser = subparsers.add_parser("cleanup", help="Prune old local loop artifacts.")
    cleanup_parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .codex-loop state.",
    )
    cleanup_parser.add_argument(
        "--keep",
        type=int,
        default=10,
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
    project_dir = Path(args.project_dir).resolve()

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

        if args.command == "doctor":
            report = run_doctor(project_dir, repair=args.repair)
            print(render_doctor_report(report))
            return 0

        if args.command == "events":
            events = load_events_timeline(
                project_dir,
                limit=args.limit,
                task_id=args.task_id,
                event_type=args.event_type,
                since=args.since,
                until=args.until,
            )
            if args.json:
                rendered = json.dumps(
                    events,
                    indent=2,
                    ensure_ascii=False,
                )
            else:
                rendered = format_events_timeline(
                    project_dir,
                    limit=args.limit,
                    task_id=args.task_id,
                    event_type=args.event_type,
                    since=args.since,
                    until=args.until,
                )
            if args.output:
                output_path = Path(args.output).resolve()
                _write_output_file(output_path, rendered)
                print(f"Wrote events to {output_path}")
            else:
                print(rendered)
            return 0

        if args.command == "cleanup":
            keep_overrides, age_overrides = _collect_cleanup_overrides(args)
            cleanup_kwargs = {
                "apply": args.apply,
                "keep": args.keep,
                "older_than_days": args.older_than_days,
                "remove_worktrees": not args.no_worktrees,
            }
            if keep_overrides:
                cleanup_kwargs["directory_keep"] = keep_overrides
            if age_overrides:
                cleanup_kwargs["directory_older_than_days"] = age_overrides
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
