from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .state_store import StateStore


AGENT_RESULT_SCHEMA = {
    "type": "object",
    "required": [
        "status",
        "summary",
        "task_id",
        "files_changed",
        "verification_expected",
        "needs_resume",
        "blockers",
        "next_action",
    ],
    "properties": {
        "status": {"type": "string", "enum": ["continue", "complete", "blocked"]},
        "summary": {"type": "string"},
        "task_id": {"type": "string"},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "verification_expected": {
            "type": "array",
            "items": {"type": "string"},
        },
        "needs_resume": {"type": "boolean"},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string"},
        "session_id": {"type": "string"},
    },
    "additionalProperties": True,
}


@dataclass(slots=True)
class TaskDraft:
    slug: str
    title: str
    markdown: str


@dataclass(slots=True)
class InitResult:
    project_name: str
    goal_summary: str
    done_when: list[str]
    spec_markdown: str
    plan_markdown: str
    tasks: list[TaskDraft]
    verification_commands: list[str]


def initialize_project(
    *,
    project_dir: Path,
    prompt: str,
    result: InitResult,
    force: bool,
    model: str = "gpt-5.4",
) -> None:
    paths = [
        project_dir / "codex-loop.yaml",
        project_dir / "spec",
        project_dir / "plan",
        project_dir / "tasks",
        project_dir / ".codex-loop",
    ]
    if not force:
        existing = [
            path
            for path in paths
            if path.exists() and (path.is_file() or any(path.iterdir()) if path.is_dir() else True)
        ]
        if existing:
            names = [str(p.relative_to(project_dir)) if p.is_relative_to(project_dir) else str(p) for p in existing]
            msg = (
                f"Refusing to overwrite existing codex-loop files: {names}\n"
                "Use --force to overwrite (WARNING: deletes all run history and state),\n"
                "or remove these files manually first."
            )
            raise FileExistsError(msg)

    (project_dir / "spec").mkdir(parents=True, exist_ok=True)
    (project_dir / "plan").mkdir(parents=True, exist_ok=True)
    (project_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (project_dir / ".codex-loop" / "logs").mkdir(parents=True, exist_ok=True)
    (project_dir / ".codex-loop" / "runs").mkdir(parents=True, exist_ok=True)
    (project_dir / ".codex-loop" / "artifacts").mkdir(parents=True, exist_ok=True)

    config = {
        "version": 1,
        "project": {"name": result.project_name},
        "goal": {"summary": result.goal_summary, "done_when": result.done_when},
        "execution": {
            "sandbox": "workspace-write",
            "approval": "never",
            "max_iterations": 30,
            "max_no_progress_iterations": 5,
            "max_consecutive_runner_failures": 3,
            "max_consecutive_verification_failures": 0,
            "max_consecutive_task_failures": 5,
            "iteration_timeout_seconds": 1800,
            "iteration_backoff_seconds": 0.0,
            "iteration_backoff_jitter_seconds": 0.0,
            "resume_fallback_to_fresh": True,
            "worktree": {"enabled": True, "branch_prefix": "codex-loop/"},
        },
        "codex": {
            "model": model,
            "use_json": True,
            "output_schema": ".codex-loop/agent_result.schema.json",
        },
        "verification": {
            "commands": result.verification_commands,
            "pass_requires_all": True,
            "timeout_seconds": 300,
        },
        "tasks": {"strategy": "sequential", "source_dir": "tasks"},
        "logging": {"save_prompts": True, "save_jsonl": True},
        "operator": {
            "events": {"default_limit": 20},
            "cleanup": {
                "keep": 10,
                "older_than_days": None,
                "directory_keep": {},
                "directory_older_than_days": {},
            },
        },
        "hooks": {
            "post_init": [],
            "pre_iteration": [],
            "post_iteration": [],
            "on_completed": [],
            "on_blocked": [],
            "failure_policy": "ignore",
            "timeout_seconds": 300,
        },
    }
    (project_dir / "codex-loop.yaml").write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (project_dir / "spec" / "001-project-spec.md").write_text(
        result.spec_markdown,
        encoding="utf-8",
    )
    (project_dir / "plan" / "001-implementation-plan.md").write_text(
        result.plan_markdown,
        encoding="utf-8",
    )
    task_ids: list[str] = []
    for index, task in enumerate(result.tasks, start=1):
        task_id = f"{index:03d}-{task.slug}"
        (project_dir / "tasks" / f"{task_id}.md").write_text(
            task.markdown,
            encoding="utf-8",
        )
        task_ids.append(task_id)

    (project_dir / ".codex-loop" / "agent_result.schema.json").write_text(
        json.dumps(AGENT_RESULT_SCHEMA, indent=2),
        encoding="utf-8",
    )
    StateStore(project_dir / ".codex-loop" / "state.json").create_initial(
        project_name=result.project_name,
        source_prompt=prompt,
        tasks=task_ids,
    )
    _ensure_gitignore(project_dir)


def _ensure_gitignore(project_dir: Path) -> None:
    """Append .codex-loop/ to .gitignore and .git/info/exclude if not already present."""
    entry = ".codex-loop/"

    gitignore = project_dir / ".gitignore"
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")
        if entry not in existing.splitlines():
            separator = "" if existing.endswith("\n") else "\n"
            gitignore.write_text(existing + separator + entry + "\n", encoding="utf-8")
    else:
        gitignore.write_text(entry + "\n", encoding="utf-8")

    # Also add to .git/info/exclude so .codex-loop/ is ignored even before
    # .gitignore is committed (works for any git repo layout).
    git_exclude = project_dir / ".git" / "info" / "exclude"
    if git_exclude.exists():
        existing = git_exclude.read_text(encoding="utf-8")
        if entry not in existing.splitlines():
            separator = "" if existing.endswith("\n") else "\n"
            git_exclude.write_text(existing + separator + entry + "\n", encoding="utf-8")
