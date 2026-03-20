from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

SUPPORTED_ARTIFACT_DIRECTORIES = frozenset({"logs", "runs", "prompts"})


def _load_yaml_or_json(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML configuration: {exc}") from exc
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
    max_consecutive_runner_failures: int = 3
    max_consecutive_verification_failures: int = 0
    max_consecutive_task_failures: int = 5
    lock_stale_seconds: int = 21600
    iteration_timeout_seconds: int = 1800
    iteration_backoff_seconds: float = 0.0
    iteration_backoff_jitter_seconds: float = 0.0
    resume_fallback_to_fresh: bool = True
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
    timeout_seconds: int = 300


@dataclass(slots=True)
class TasksConfig:
    strategy: str = "sequential"
    source_dir: str = "tasks"


@dataclass(slots=True)
class LoggingConfig:
    save_prompts: bool = True
    save_jsonl: bool = True


@dataclass(slots=True)
class HooksConfig:
    post_init: list[str] = field(default_factory=list)
    pre_iteration: list[str] = field(default_factory=list)
    post_iteration: list[str] = field(default_factory=list)
    on_completed: list[str] = field(default_factory=list)
    on_blocked: list[str] = field(default_factory=list)
    failure_policy: str = "ignore"
    timeout_seconds: int = 300


@dataclass(slots=True)
class EventsOperatorConfig:
    default_limit: int = 20


@dataclass(slots=True)
class CleanupOperatorConfig:
    keep: int = 10
    older_than_days: int | None = None
    directory_keep: dict[str, int] = field(default_factory=dict)
    directory_older_than_days: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class OperatorConfig:
    events: EventsOperatorConfig = field(default_factory=EventsOperatorConfig)
    cleanup: CleanupOperatorConfig = field(default_factory=CleanupOperatorConfig)


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
    hooks: HooksConfig = field(default_factory=HooksConfig)
    operator: OperatorConfig = field(default_factory=OperatorConfig)

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
            max_consecutive_runner_failures=int(
                execution_data.get("max_consecutive_runner_failures", 3)
            ),
            max_consecutive_verification_failures=int(
                execution_data.get("max_consecutive_verification_failures", 0)
            ),
            max_consecutive_task_failures=int(
                execution_data.get("max_consecutive_task_failures", 5)
            ),
            lock_stale_seconds=int(execution_data.get("lock_stale_seconds", 21600)),
            iteration_timeout_seconds=int(
                execution_data.get("iteration_timeout_seconds", 1800)
            ),
            iteration_backoff_seconds=float(
                execution_data.get("iteration_backoff_seconds", 0.0)
            ),
            iteration_backoff_jitter_seconds=float(
                execution_data.get("iteration_backoff_jitter_seconds", 0.0)
            ),
            resume_fallback_to_fresh=bool(
                execution_data.get("resume_fallback_to_fresh", True)
            ),
            worktree=worktree,
        )
        codex = CodexConfig(**data.get("codex", {}))
        verification = VerificationConfig(**data.get("verification", {}))
        tasks = TasksConfig(**data.get("tasks", {}))
        logging = LoggingConfig(**data.get("logging", {}))
        hooks = HooksConfig(**data.get("hooks", {}))
        operator_data = data.get("operator", {})
        operator = OperatorConfig(
            events=EventsOperatorConfig(**operator_data.get("events", {})),
            cleanup=CleanupOperatorConfig(**operator_data.get("cleanup", {})),
        )
        config = cls(
            project_dir=project_dir,
            project=project,
            goal=goal,
            execution=execution,
            codex=codex,
            verification=verification,
            tasks=tasks,
            logging=logging,
            hooks=hooks,
            operator=operator,
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
        if self.execution.max_iterations <= 0:
            msg = "execution.max_iterations must be greater than zero."
            raise ValueError(msg)
        if self.execution.max_no_progress_iterations <= 0:
            msg = "execution.max_no_progress_iterations must be greater than zero."
            raise ValueError(msg)
        if self.execution.max_consecutive_runner_failures < 0:
            msg = "execution.max_consecutive_runner_failures must not be negative."
            raise ValueError(msg)
        if self.execution.max_consecutive_verification_failures < 0:
            msg = "execution.max_consecutive_verification_failures must not be negative."
            raise ValueError(msg)
        if self.execution.max_consecutive_task_failures < 0:
            msg = "execution.max_consecutive_task_failures must not be negative."
            raise ValueError(msg)
        if self.execution.lock_stale_seconds <= 0:
            msg = "execution.lock_stale_seconds must be greater than zero."
            raise ValueError(msg)
        if self.execution.iteration_timeout_seconds <= 0:
            msg = "execution.iteration_timeout_seconds must be greater than zero."
            raise ValueError(msg)
        if self.execution.iteration_backoff_seconds < 0:
            msg = "execution.iteration_backoff_seconds must not be negative."
            raise ValueError(msg)
        if self.execution.iteration_backoff_jitter_seconds < 0:
            msg = "execution.iteration_backoff_jitter_seconds must not be negative."
            raise ValueError(msg)
        if self.verification.timeout_seconds <= 0:
            msg = "verification.timeout_seconds must be greater than zero."
            raise ValueError(msg)
        if self.hooks.timeout_seconds <= 0:
            msg = "hooks.timeout_seconds must be greater than zero."
            raise ValueError(msg)
        if self.hooks.failure_policy not in {"ignore", "block"}:
            msg = f"Unsupported hooks.failure_policy: {self.hooks.failure_policy}"
            raise ValueError(msg)
        if self.tasks.strategy != "sequential":
            msg = f"Unsupported tasks.strategy: {self.tasks.strategy}"
            raise ValueError(msg)
        if not self.tasks.source_dir.strip():
            msg = "tasks.source_dir must not be empty."
            raise ValueError(msg)
        if self.operator.events.default_limit <= 0:
            msg = "operator.events.default_limit must be greater than zero."
            raise ValueError(msg)
        if self.operator.cleanup.keep < 0:
            msg = "operator.cleanup.keep must not be negative."
            raise ValueError(msg)
        if (
            self.operator.cleanup.older_than_days is not None
            and self.operator.cleanup.older_than_days < 0
        ):
            msg = "operator.cleanup.older_than_days must not be negative."
            raise ValueError(msg)
        for directory_name, value in self.operator.cleanup.directory_keep.items():
            if directory_name not in SUPPORTED_ARTIFACT_DIRECTORIES:
                msg = f"Unsupported cleanup directory override: {directory_name}"
                raise ValueError(msg)
            if value < 0:
                msg = f"operator.cleanup.directory_keep[{directory_name}] must not be negative."
                raise ValueError(msg)
        for (
            directory_name,
            value,
        ) in self.operator.cleanup.directory_older_than_days.items():
            if directory_name not in SUPPORTED_ARTIFACT_DIRECTORIES:
                msg = f"Unsupported cleanup directory override: {directory_name}"
                raise ValueError(msg)
            if value < 0:
                msg = (
                    f"operator.cleanup.directory_older_than_days[{directory_name}] "
                    "must not be negative."
                )
                raise ValueError(msg)
