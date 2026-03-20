from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import subprocess

from .git_ops import remove_worktree, resolve_repo_root
from .state_store import StateStore

ARTIFACT_DIR_NAMES = ("logs", "runs", "prompts")


@dataclass(slots=True)
class CleanupReport:
    dry_run: bool
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    removed_worktrees: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _artifact_directories(project_dir: Path) -> list[Path]:
    base = project_dir / ".codex-loop"
    return [base / name for name in ARTIFACT_DIR_NAMES]


def _relative_to_project(project_dir: Path, path: Path) -> str:
    return str(path.relative_to(project_dir))


def _is_older_than(
    path: Path,
    *,
    older_than_days: int | None,
    now_timestamp: float | None,
) -> bool:
    if older_than_days is None:
        return True
    current_timestamp = (
        float(now_timestamp)
        if now_timestamp is not None
        else datetime.now(UTC).timestamp()
    )
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return True
    age_seconds = current_timestamp - mtime
    threshold_seconds = older_than_days * 24 * 60 * 60
    return age_seconds >= threshold_seconds


def _cleanup_directory(
    project_dir: Path,
    directory_name: str,
    directory: Path,
    *,
    keep: int,
    older_than_days: int | None,
    now_timestamp: float | None,
    apply: bool,
    report: CleanupReport,
) -> None:
    if not directory.exists():
        return
    _entries = []
    for _p in directory.iterdir():
        if not _p.is_file():
            continue
        try:
            _mtime = _p.stat().st_mtime
        except FileNotFoundError:
            continue
        _entries.append((_mtime, _p.name, _p))
    files = [_p for _, _, _p in sorted(_entries)]
    if len(files) <= keep:
        report.kept.extend(_relative_to_project(project_dir, path) for path in files)
        return
    protected = set(files[-keep:] if keep > 0 else [])
    for path in files:
        relative_path = _relative_to_project(project_dir, path)
        if path in protected or not _is_older_than(
            path,
            older_than_days=older_than_days,
            now_timestamp=now_timestamp,
        ):
            report.kept.append(relative_path)
            continue
        report.removed.append(relative_path)
        if apply:
            path.unlink(missing_ok=True)


def run_cleanup(
    project_dir: Path,
    *,
    apply: bool,
    keep: int,
    older_than_days: int | None = None,
    remove_worktrees: bool,
    now_timestamp: float | None = None,
    directory_keep: dict[str, int] | None = None,
    directory_older_than_days: dict[str, int] | None = None,
) -> CleanupReport:
    report = CleanupReport(dry_run=not apply)
    keep_overrides = directory_keep or {}
    age_overrides = directory_older_than_days or {}
    for directory_name, directory in zip(
        ARTIFACT_DIR_NAMES,
        _artifact_directories(project_dir),
        strict=True,
    ):
        _cleanup_directory(
            project_dir,
            directory_name,
            directory,
            keep=keep_overrides.get(directory_name, keep),
            older_than_days=age_overrides.get(directory_name, older_than_days),
            now_timestamp=now_timestamp,
            apply=apply,
            report=report,
        )

    if not remove_worktrees:
        return report

    try:
        state = StateStore(project_dir / ".codex-loop" / "state.json").load()
    except (FileNotFoundError, OSError):
        state = {}
    active_worktree = state.get("meta", {}).get("worktree_path")
    try:
        repo_root = resolve_repo_root(project_dir)
    except (FileNotFoundError, OSError, subprocess.CalledProcessError) as exc:
        report.warnings.append(f"Skipping worktree cleanup: {exc}")
        return report

    worktree_root = repo_root.parent / ".codex-loop-worktrees" / repo_root.name
    if not worktree_root.exists():
        return report

    active_path = Path(active_worktree).resolve() if active_worktree else None
    for path in sorted(candidate for candidate in worktree_root.iterdir() if candidate.is_dir()):
        if active_path is not None and path.resolve() == active_path:
            continue
        if not _is_older_than(
            path,
            older_than_days=older_than_days,
            now_timestamp=now_timestamp,
        ):
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
