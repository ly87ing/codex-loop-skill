from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


def _load_yaml_or_json(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        if isinstance(loaded, dict):
            return loaded
    except ModuleNotFoundError:
        pass
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        msg = "Configuration must be a mapping."
        raise ValueError(msg)
    return loaded


@dataclass(slots=True)
class ProjectConfig:
    name: str = "unnamed-project"


@dataclass(slots=True)
class GoalConfig:
    summary: str
    done_when: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorktreeConfig:
    enabled: bool = True
    branch_prefix: str = "codex-loop/"


@dataclass(slots=True)
class ExecutionConfig:
    sandbox: str = "workspace-write"
    approval: str = "never"
    max_iterations: int = 30
    max_no_progress_iterations: int = 5
    lock_stale_seconds: int = 21600
    worktree: WorktreeConfig = field(default_factory=WorktreeConfig)


@dataclass(slots=True)
class CodexConfig:
    model: str = "gpt-5.4"
    use_json: bool = True
    output_schema: str = ".codex-loop/agent_result.schema.json"


@dataclass(slots=True)
class VerificationConfig:
    commands: list[str] = field(default_factory=list)
    pass_requires_all: bool = True


@dataclass(slots=True)
class TasksConfig:
    strategy: str = "sequential"
    source_dir: str = "tasks"


@dataclass(slots=True)
class LoggingConfig:
    save_prompts: bool = True
    save_jsonl: bool = True


@dataclass(slots=True)
class CodexLoopConfig:
    project_dir: Path
    project: ProjectConfig
    goal: GoalConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    codex: CodexConfig = field(default_factory=CodexConfig)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    tasks: TasksConfig = field(default_factory=TasksConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_file(cls, path: Path) -> "CodexLoopConfig":
        data = _load_yaml_or_json(path.read_text(encoding="utf-8"))
        return cls.from_dict(data, path.parent)

    @classmethod
    def from_dict(cls, data: dict[str, Any], project_dir: Path) -> "CodexLoopConfig":
        project = ProjectConfig(**data.get("project", {}))
        goal = GoalConfig(**data.get("goal", {"summary": ""}))
        execution_data = data.get("execution", {})
        worktree = WorktreeConfig(**execution_data.get("worktree", {}))
        execution = ExecutionConfig(
            sandbox=execution_data.get("sandbox", "workspace-write"),
            approval=execution_data.get("approval", "never"),
            max_iterations=int(execution_data.get("max_iterations", 30)),
            max_no_progress_iterations=int(
                execution_data.get("max_no_progress_iterations", 5)
            ),
            lock_stale_seconds=int(execution_data.get("lock_stale_seconds", 21600)),
            worktree=worktree,
        )
        codex = CodexConfig(**data.get("codex", {}))
        verification = VerificationConfig(**data.get("verification", {}))
        tasks = TasksConfig(**data.get("tasks", {}))
        logging = LoggingConfig(**data.get("logging", {}))
        config = cls(
            project_dir=project_dir,
            project=project,
            goal=goal,
            execution=execution,
            codex=codex,
            verification=verification,
            tasks=tasks,
            logging=logging,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.project.name.strip():
            msg = "project.name must not be empty."
            raise ValueError(msg)
        if not self.goal.summary.strip():
            msg = "goal.summary must not be empty."
            raise ValueError(msg)
        if not self.goal.done_when:
            msg = "goal.done_when must include at least one completion criterion."
            raise ValueError(msg)
        if not self.verification.commands:
            msg = "verification.commands must contain at least one command."
            raise ValueError(msg)
        if self.execution.max_iterations <= 0:
            msg = "execution.max_iterations must be greater than zero."
            raise ValueError(msg)
        if self.execution.max_no_progress_iterations <= 0:
            msg = "execution.max_no_progress_iterations must be greater than zero."
            raise ValueError(msg)
        if self.execution.lock_stale_seconds <= 0:
            msg = "execution.lock_stale_seconds must be greater than zero."
            raise ValueError(msg)
        if self.tasks.strategy != "sequential":
            msg = f"Unsupported tasks.strategy: {self.tasks.strategy}"
            raise ValueError(msg)
        if not self.tasks.source_dir.strip():
            msg = "tasks.source_dir must not be empty."
            raise ValueError(msg)
