from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import shutil
import subprocess


@dataclass(slots=True)
class WorktreeInfo:
    repo_root: Path
    branch_name: str
    path: Path


def _run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def resolve_repo_root(project_dir: Path) -> Path:
    return Path(_run_git(project_dir, "rev-parse", "--show-toplevel"))


def ensure_local_state_ignored(repo_root: Path) -> None:
    exclude_file = repo_root / ".git" / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
    marker = ".codex-loop/"
    if marker not in existing.splitlines():
        updated = existing + ("\n" if existing and not existing.endswith("\n") else "") + marker + "\n"
        tmp_path = exclude_file.with_suffix(exclude_file.suffix + ".tmp")
        tmp_path.write_text(updated, encoding="utf-8")
        tmp_path.replace(exclude_file)


def sanitize_branch_name(branch_name: str) -> str:
    return branch_name.replace("/", "-").replace(" ", "-")


def build_worktree_path(repo_root: Path, branch_name: str) -> Path:
    return repo_root.parent / ".codex-loop-worktrees" / repo_root.name / sanitize_branch_name(branch_name)


def resolve_project_working_directory(
    *,
    project_dir: Path,
    repo_root: Path,
    worktree_root: Path,
) -> Path:
    relative = project_dir.relative_to(repo_root)
    return worktree_root / relative


def create_worktree(
    repo_root: Path,
    branch_prefix: str,
    task_id: str,
    existing_path: str | None = None,
    existing_branch: str | None = None,
) -> WorktreeInfo:
    if existing_path and existing_branch:
        path = Path(existing_path)
        if path.exists():
            return WorktreeInfo(repo_root=repo_root, branch_name=existing_branch, path=path)
        # Worktree directory removed but branch may still exist — try to
        # re-attach. Fall through to a fresh worktree if the branch is gone.
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "worktree", "add", str(path), existing_branch],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            return WorktreeInfo(repo_root=repo_root, branch_name=existing_branch, path=path)
        except subprocess.CalledProcessError:
            pass  # Branch deleted — fall through to create a fresh worktree

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    branch_name = f"{branch_prefix}{task_id}-{timestamp}"
    path = build_worktree_path(repo_root, branch_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(path)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return WorktreeInfo(repo_root=repo_root, branch_name=branch_name, path=path)


def remove_worktree(repo_root: Path, path: Path) -> None:
    if not path.exists():
        return
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        shutil.rmtree(path, ignore_errors=True)
