from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .codex_runner import CodexRunner
from .init_flow import initialize_project
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_dir = Path(args.project_dir).resolve()

    if args.command == "init":
        runner = CodexRunner(project_dir)
        result = runner.initialize_from_prompt(prompt=args.prompt, model=args.model)
        initialize_project(
            project_dir=project_dir,
            prompt=args.prompt,
            result=result,
            force=args.force,
        )
        print(f"Initialized codex-loop files in {project_dir}")
        return 0

    if args.command == "run":
        outcome = run_project(project_dir)
        print(outcome.value)
        return 0 if outcome.value == "completed" else 2

    if args.command == "status":
        state = StateStore(project_dir / ".codex-loop" / "state.json").load()
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

