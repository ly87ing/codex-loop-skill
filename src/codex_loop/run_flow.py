from __future__ import annotations

from pathlib import Path

from .codex_runner import CodexRunner
from .config import CodexLoopConfig
from .git_ops import create_worktree, ensure_local_state_ignored, resolve_repo_root
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


def run_project(project_dir: Path) -> LoopOutcome:
    config = CodexLoopConfig.from_file(project_dir / "codex-loop.yaml")
    state_store = StateStore(project_dir / ".codex-loop" / "state.json")
    repo_root = resolve_repo_root(project_dir)
    ensure_local_state_ignored(repo_root)

    working_directory = project_dir
    state = state_store.load()
    if config.execution.worktree.enabled:
        worktree = create_worktree(
            repo_root=repo_root,
            branch_prefix=config.execution.worktree.branch_prefix,
            task_id=next(iter(state["tasks"])),
            existing_path=state["meta"].get("worktree_path"),
            existing_branch=state["meta"].get("worktree_branch"),
        )
        working_directory = worktree.path
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
    )
    return supervisor.run()

