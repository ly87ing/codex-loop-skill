from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess

from .git_ops import remove_worktree, resolve_repo_root
from .state_store import StateStore


@dataclass(slots=True)
class CleanupReport:
    dry_run: bool
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    removed_worktrees: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _artifact_directories(project_dir: Path) -> list[Path]:
    base = project_dir / ".codex-loop"
    return [
        base / "logs",
        base / "runs",
        base / "prompts",
    ]


def _relative_to_project(project_dir: Path, path: Path) -> str:
    return str(path.relative_to(project_dir))


def _cleanup_directory(
    project_dir: Path,
    directory: Path,
    *,
    keep: int,
    apply: bool,
    report: CleanupReport,
) -> None:
    if not directory.exists():
        return
    files = sorted(path for path in directory.iterdir() if path.is_file())
    if len(files) <= keep:
        report.kept.extend(_relative_to_project(project_dir, path) for path in files)
        return
    removable = files[:-keep] if keep > 0 else files
    surviving = files[-keep:] if keep > 0 else []
    for path in removable:
        report.removed.append(_relative_to_project(project_dir, path))
        if apply:
            path.unlink(missing_ok=True)
    report.kept.extend(_relative_to_project(project_dir, path) for path in surviving)


def run_cleanup(
    project_dir: Path,
    *,
    apply: bool,
    keep: int,
    remove_worktrees: bool,
) -> CleanupReport:
    report = CleanupReport(dry_run=not apply)
    for directory in _artifact_directories(project_dir):
        _cleanup_directory(
            project_dir,
            directory,
            keep=keep,
            apply=apply,
            report=report,
        )

    if not remove_worktrees:
        return report

    state = StateStore(project_dir / ".codex-loop" / "state.json").load()
    active_worktree = state.get("meta", {}).get("worktree_path")
    try:
        repo_root = resolve_repo_root(project_dir)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        report.warnings.append(f"Skipping worktree cleanup: {exc}")
        return report

    worktree_root = repo_root.parent / ".codex-loop-worktrees" / repo_root.name
    if not worktree_root.exists():
        return report

    active_path = Path(active_worktree).resolve() if active_worktree else None
    for path in sorted(candidate for candidate in worktree_root.iterdir() if candidate.is_dir()):
        if active_path is not None and path.resolve() == active_path:
            continue
        report.removed_worktrees.append(path)
        if apply:
            remove_worktree(repo_root, path)
    return report


def render_cleanup_report(report: CleanupReport) -> str:
    lines = [
        f"mode: {'apply' if not report.dry_run else 'dry-run'}",
        f"removed: {len(report.removed)}",
        f"kept: {len(report.kept)}",
        f"removed_worktrees: {len(report.removed_worktrees)}",
    ]
    if report.removed:
        lines.append("removed_entries:")
        lines.extend(report.removed)
    if report.removed_worktrees:
        lines.append("removed_worktree_paths:")
        lines.extend(str(path) for path in report.removed_worktrees)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(report.warnings)
    return "\n".join(lines)
