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
            msg = f"Refusing to overwrite existing codex-loop files: {existing}"
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
            "iteration_timeout_seconds": 1800,
            "iteration_backoff_seconds": 0.0,
            "iteration_backoff_jitter_seconds": 0.0,
            "resume_fallback_to_fresh": True,
            "worktree": {"enabled": True, "branch_prefix": "codex-loop/"},
        },
        "codex": {
            "model": "gpt-5.4",
            "use_json": True,
            "output_schema": ".codex-loop/agent_result.schema.json",
        },
        "verification": {
            "commands": result.verification_commands,
            "pass_requires_all": True,
        },
        "tasks": {"strategy": "sequential", "source_dir": "tasks"},
        "logging": {"save_prompts": True, "save_jsonl": True},
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
