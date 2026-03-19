from __future__ import annotations

from pathlib import Path
import time
from typing import Callable

from .codex_runner import CodexRunner
from .config import CodexLoopConfig
from .doctor import run_doctor
from .git_ops import (
    create_worktree,
    ensure_local_state_ignored,
    resolve_project_working_directory,
    resolve_repo_root,
)
from .hooks import HookRunner
from .run_lock import RunLock
from .state_store import StateStore
from .supervisor import LoopOutcome, Supervisor
from .task_graph import TaskGraph
from .verifier import Verifier


class LoopTaskRunner:
    def __init__(
        self,
        *,
        codex_runner: CodexRunner,
        config: CodexLoopConfig,
        state_store: StateStore,
        working_directory: Path,
    ) -> None:
        self.codex_runner = codex_runner
        self.config = config
        self.state_store = state_store
        self.working_directory = working_directory

    def run_task(self, *, task, resume_session):
        state = self.state_store.load()
        return self.codex_runner.run_task(
            config=self.config,
            task=task,
            state=state,
            working_directory=self.working_directory,
            resume_session=resume_session,
        )


def retry_blocked_tasks_for_retry(project_dir: Path) -> bool:
    store = StateStore(project_dir / ".codex-loop" / "state.json")
    state = store.load()
    tasks = state.get("tasks", {})
    if not any(task.get("status") == "blocked" for task in tasks.values()):
        return False
    store.requeue_blocked_tasks()
    return True


def run_project(project_dir: Path) -> LoopOutcome:
    config = CodexLoopConfig.from_file(project_dir / "codex-loop.yaml")
    report = run_doctor(project_dir, repair=True)
    if report.errors:
        msg = "; ".join(report.errors)
        raise RuntimeError(f"codex-loop doctor found blocking issues: {msg}")
    state_store = StateStore(project_dir / ".codex-loop" / "state.json")
    repo_root = resolve_repo_root(project_dir)
    ensure_local_state_ignored(repo_root)
    lock = RunLock(
        project_dir / ".codex-loop" / "run.lock",
        stale_seconds=config.execution.lock_stale_seconds,
    )
    with lock:
        working_directory = project_dir
        state = state_store.load()
        if config.execution.worktree.enabled:
            active_task_id = next(
                (
                    task_id
                    for task_id, task_state in state["tasks"].items()
                    if task_state["status"] in {"ready", "in_progress"}
                ),
                next(iter(state["tasks"]), "project"),
            )
            worktree = create_worktree(
                repo_root=repo_root,
                branch_prefix=config.execution.worktree.branch_prefix,
                task_id=active_task_id,
                existing_path=state["meta"].get("worktree_path"),
                existing_branch=state["meta"].get("worktree_branch"),
            )
            working_directory = resolve_project_working_directory(
                project_dir=project_dir,
                repo_root=repo_root,
                worktree_root=worktree.path,
            )
            state["meta"]["worktree_path"] = str(worktree.path)
            state["meta"]["worktree_branch"] = worktree.branch_name
            state_store.save(state)

        runner = LoopTaskRunner(
            codex_runner=CodexRunner(project_dir),
            config=config,
            state_store=state_store,
            working_directory=working_directory,
        )
        supervisor = Supervisor(
            config=config,
            state_store=state_store,
            task_graph=TaskGraph(project_dir / config.tasks.source_dir),
            runner=runner,
            verifier=Verifier(),
            working_directory=working_directory,
            hook_runner=HookRunner(project_dir / ".codex-loop" / "hooks"),
        )
        return supervisor.run()


def run_project_continuously(
    project_dir: Path,
    *,
    retry_blocked: bool = False,
    cycle_sleep_seconds: float = 60.0,
    max_cycles: int | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    run_once: Callable[[Path], LoopOutcome] | None = None,
) -> LoopOutcome:
    sleep = sleep_fn or time.sleep
    run_single = run_once or run_project
    cycles = 0
    while True:
        if retry_blocked:
            retry_blocked_tasks_for_retry(project_dir)
        outcome = run_single(project_dir)
        cycles += 1
        if outcome == LoopOutcome.COMPLETED:
            return outcome
        if not retry_blocked:
            return outcome
        if max_cycles is not None and cycles >= max_cycles:
            return outcome
        sleep(cycle_sleep_seconds)
