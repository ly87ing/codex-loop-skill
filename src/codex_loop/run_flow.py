from __future__ import annotations

import json as _json
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable

from .codex_runner import CodexRunner
from .config import CodexLoopConfig
from .daemon_manager import write_daemon_heartbeat
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


_HEARTBEAT_INTERVAL_SECONDS = 60


def _run_supervisor_with_heartbeat(
    supervisor: object,
    heartbeat_path: Path | None,
) -> LoopOutcome:
    """Run supervisor.run() while a background thread keeps the heartbeat file
    updated every 60 seconds.  This prevents the watchdog from misreading a
    long-running codex exec call (up to 1800 s) as a dead process."""
    if heartbeat_path is None:
        return supervisor.run()  # type: ignore[union-attr]

    stop_event = threading.Event()

    def _beat() -> None:
        while not stop_event.wait(_HEARTBEAT_INTERVAL_SECONDS):
            try:
                # Read the current cycle from the existing heartbeat so we
                # don't clobber the cycle counter written by run_project_continuously.
                existing_cycle = 0
                if heartbeat_path.exists():
                    try:
                        existing_cycle = _json.loads(
                            heartbeat_path.read_text(encoding="utf-8")
                        ).get("cycle", 0)
                    except Exception:  # noqa: BLE001
                        pass
                write_daemon_heartbeat(
                    heartbeat_path,
                    phase="running",
                    cycle=existing_cycle,
                )
            except Exception:  # noqa: BLE001
                pass

    beat_thread = threading.Thread(target=_beat, daemon=True)
    beat_thread.start()
    try:
        return supervisor.run()  # type: ignore[union-attr]
    finally:
        stop_event.set()
        beat_thread.join(timeout=5)


def retry_blocked_tasks_for_retry(project_dir: Path) -> bool:
    store = StateStore(project_dir / ".codex-loop" / "state.json")
    try:
        state = store.load()
    except (FileNotFoundError, OSError):
        return False
    tasks = state.get("tasks", {})
    if not any(task.get("status") == "blocked" for task in tasks.values()):
        return False
    store.requeue_blocked_tasks()
    return True


def run_project(
    project_dir: Path,
    *,
    heartbeat_path: Path | None = None,
) -> LoopOutcome:
    config = CodexLoopConfig.from_file(project_dir / "codex-loop.yaml")
    report = run_doctor(project_dir, repair=True)
    if report.errors:
        msg = "; ".join(report.errors)
        raise RuntimeError(f"codex-loop doctor found blocking issues: {msg}")
    for warning in report.warnings:
        print(f"Warning: {warning}", flush=True)
    for fixed in report.fixed:
        print(f"Auto-fixed: {fixed}", flush=True)
    state_store = StateStore(project_dir / ".codex-loop" / "state.json")
    try:
        repo_root = resolve_repo_root(project_dir)
    except subprocess.CalledProcessError:
        raise RuntimeError(
            f"{project_dir} is not inside a Git repository. "
            "Initialize one with: git init && git add -A && git commit -m 'init'"
        )
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
            try:
                worktree = create_worktree(
                    repo_root=repo_root,
                    branch_prefix=config.execution.worktree.branch_prefix,
                    task_id=active_task_id,
                    existing_path=state["meta"].get("worktree_path"),
                    existing_branch=state["meta"].get("worktree_branch"),
                )
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()
                hint = ""
                if "no commits" in stderr or "does not have any commits" in stderr:
                    hint = (
                        "\nHint: your repository has no commits yet. "
                        "Run: git add -A && git commit -m 'init'"
                    )
                raise RuntimeError(
                    f"Failed to create git worktree: {stderr}{hint}"
                ) from exc
            working_directory = resolve_project_working_directory(
                project_dir=project_dir,
                repo_root=repo_root,
                worktree_root=worktree.path,
            )
            state["meta"]["worktree_path"] = str(worktree.path)
            state["meta"]["worktree_branch"] = worktree.branch_name
            state_store.save(state)
            print(
                f"Codex working in: {working_directory}"
                " (isolated Git branch — your project files are unchanged until you merge)",
                flush=True,
            )
            # Warn if key loop files are not committed — Codex runs in an isolated
            # worktree built from the latest commit, so uncommitted files are invisible.
            try:
                _untracked = subprocess.run(
                    ["git", "-C", str(repo_root), "ls-files", "--others", "--exclude-standard",
                     "tasks/"],
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip()
                _modified = subprocess.run(
                    ["git", "-C", str(repo_root), "diff", "--name-only", "HEAD", "--",
                     "tasks/"],
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip()
                _staged = subprocess.run(
                    ["git", "-C", str(repo_root), "diff", "--name-only", "--cached", "--",
                     "tasks/"],
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip()
                _uncommitted = list(dict.fromkeys(
                    f for f in (_untracked + "\n" + _modified + "\n" + _staged).splitlines() if f
                ))
                if _uncommitted:
                    print(
                        "Warning: these task files are not committed and will be invisible to Codex:",
                        flush=True,
                    )
                    for _f in _uncommitted:
                        print(f"  {_f}", flush=True)
                    print(
                        "  Codex runs in an isolated Git worktree built from your latest commit.",
                        flush=True,
                    )
                    print(
                        "  Commit first, then re-run: git add -A && git commit -m 'add codex-loop files'",
                        flush=True,
                    )
            except Exception:  # noqa: BLE001
                pass

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
        return _run_supervisor_with_heartbeat(supervisor, heartbeat_path)


def run_project_continuously(
    project_dir: Path,
    *,
    retry_blocked: bool = False,
    retry_errors: bool = False,
    max_error_retries: int | None = None,
    cycle_sleep_seconds: float = 60.0,
    max_cycles: int | None = None,
    heartbeat_path: Path | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    run_once: Callable[[Path], LoopOutcome] | None = None,
) -> LoopOutcome:
    sleep = sleep_fn or time.sleep
    _run_once = run_once
    cycles = 0
    error_count = 0

    def run_single(p: Path) -> LoopOutcome:
        if _run_once is not None:
            return _run_once(p)
        return run_project(p, heartbeat_path=heartbeat_path)

    while True:
        next_cycle = cycles + 1
        if heartbeat_path is not None:
            write_daemon_heartbeat(
                heartbeat_path,
                phase="running",
                cycle=next_cycle,
                error_count=error_count,
            )
        if retry_blocked:
            retry_blocked_tasks_for_retry(project_dir)
        try:
            outcome = run_single(project_dir)
        except (FileNotFoundError, OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
            error_count += 1
            if heartbeat_path is not None:
                write_daemon_heartbeat(
                    heartbeat_path,
                    phase="error",
                    cycle=next_cycle,
                    outcome="error",
                    error_count=error_count,
                    last_error=str(exc),
                )
            if not retry_errors:
                raise
            if max_error_retries is not None and error_count >= max_error_retries:
                return LoopOutcome.BLOCKED
            sleep(cycle_sleep_seconds)
            continue
        cycles += 1
        if heartbeat_path is not None:
            write_daemon_heartbeat(
                heartbeat_path,
                phase="completed" if outcome == LoopOutcome.COMPLETED else "blocked",
                cycle=cycles,
                outcome=outcome.value,
                error_count=error_count,
            )
        if outcome == LoopOutcome.COMPLETED:
            return outcome
        if not retry_blocked:
            return outcome
        if max_cycles is not None and cycles >= max_cycles:
            return outcome
        sleep(cycle_sleep_seconds)
