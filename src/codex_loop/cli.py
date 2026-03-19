from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .codex_runner import CodexRunner
from .config import CodexLoopConfig
from .doctor import render_doctor_report, run_doctor
from .hooks import HookRunner
from .init_flow import initialize_project
from .reporting import format_status_summary, tail_log_lines
from .run_flow import run_project
from .state_store import StateStore


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
