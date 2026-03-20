from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_loop.cleanup import run_cleanup
from codex_loop.state_store import StateStore


class CleanupTests(unittest.TestCase):
    def test_cleanup_removes_old_artifacts_and_stale_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_store = StateStore(root / ".codex-loop" / "state.json")
            state = state_store.create_initial("demo", "Build demo", ["001-foundation"])

            logs_dir = root / ".codex-loop" / "logs"
            runs_dir = root / ".codex-loop" / "runs"
            prompts_dir = root / ".codex-loop" / "prompts"
            for directory in (logs_dir, runs_dir, prompts_dir):
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "0001-old.txt").write_text("old", encoding="utf-8")
                (directory / "0002-new.txt").write_text("new", encoding="utf-8")

            repo_root = root / "repo"
            repo_root.mkdir()
            active_worktree = repo_root.parent / ".codex-loop-worktrees" / repo_root.name / "active"
            stale_worktree = repo_root.parent / ".codex-loop-worktrees" / repo_root.name / "stale"
            active_worktree.mkdir(parents=True, exist_ok=True)
            stale_worktree.mkdir(parents=True, exist_ok=True)
            state["meta"]["worktree_path"] = str(active_worktree)
            state_store.save(state)

            removed_worktrees: list[Path] = []

            with (
                patch("codex_loop.cleanup.resolve_repo_root", return_value=repo_root),
                patch(
                    "codex_loop.cleanup.remove_worktree",
                    side_effect=lambda repo_root, path: removed_worktrees.append(path),
                ),
            ):
                report = run_cleanup(root, apply=True, keep=1, remove_worktrees=True)

            self.assertIn(".codex-loop/logs/0001-old.txt", report.removed)
            self.assertIn(".codex-loop/runs/0001-old.txt", report.removed)
            self.assertIn(".codex-loop/prompts/0001-old.txt", report.removed)
            self.assertFalse((logs_dir / "0001-old.txt").exists())
            self.assertTrue((logs_dir / "0002-new.txt").exists())
            self.assertEqual(removed_worktrees, [stale_worktree])

    def test_cleanup_can_preserve_recent_files_with_age_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_store = StateStore(root / ".codex-loop" / "state.json")
            state_store.create_initial("demo", "Build demo", ["001-foundation"])

            logs_dir = root / ".codex-loop" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            old_log = logs_dir / "0001-old.txt"
            new_log = logs_dir / "0002-new.txt"
            old_log.write_text("old", encoding="utf-8")
            new_log.write_text("new", encoding="utf-8")
            old_timestamp = 1_700_000_000
            new_timestamp = 1_800_000_000
            os.utime(old_log, (old_timestamp, old_timestamp))
            os.utime(new_log, (new_timestamp, new_timestamp))

            report = run_cleanup(
                root,
                apply=True,
                keep=0,
                older_than_days=365,
                remove_worktrees=False,
                now_timestamp=1_800_000_000,
            )

            self.assertIn(".codex-loop/logs/0001-old.txt", report.removed)
            self.assertIn(".codex-loop/logs/0002-new.txt", report.kept)
            self.assertFalse(old_log.exists())
            self.assertTrue(new_log.exists())

    def test_cleanup_respects_directory_specific_retention_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_store = StateStore(root / ".codex-loop" / "state.json")
            state_store.create_initial("demo", "Build demo", ["001-foundation"])

            logs_dir = root / ".codex-loop" / "logs"
            runs_dir = root / ".codex-loop" / "runs"
            prompts_dir = root / ".codex-loop" / "prompts"
            for directory in (logs_dir, runs_dir, prompts_dir):
                directory.mkdir(parents=True, exist_ok=True)

            log_file = logs_dir / "0001-log.txt"
            run_file = runs_dir / "0001-run.txt"
            prompt_old = prompts_dir / "0001-old.txt"
            prompt_new = prompts_dir / "0002-new.txt"
            log_file.write_text("log", encoding="utf-8")
            run_file.write_text("run", encoding="utf-8")
            prompt_old.write_text("old", encoding="utf-8")
            prompt_new.write_text("new", encoding="utf-8")

            old_timestamp = 1_700_000_000
            new_timestamp = 1_800_000_000
            os.utime(log_file, (new_timestamp, new_timestamp))
            os.utime(run_file, (old_timestamp, old_timestamp))
            os.utime(prompt_old, (old_timestamp, old_timestamp))
            os.utime(prompt_new, (new_timestamp, new_timestamp))

            report = run_cleanup(
                root,
                apply=True,
                keep=0,
                older_than_days=0,
                remove_worktrees=False,
                now_timestamp=1_800_000_000,
                directory_keep={"logs": 1},
                directory_older_than_days={"prompts": 365},
            )

            self.assertIn(".codex-loop/logs/0001-log.txt", report.kept)
            self.assertIn(".codex-loop/runs/0001-run.txt", report.removed)
            self.assertIn(".codex-loop/prompts/0001-old.txt", report.removed)
            self.assertIn(".codex-loop/prompts/0002-new.txt", report.kept)
            self.assertTrue(log_file.exists())
            self.assertFalse(run_file.exists())
            self.assertFalse(prompt_old.exists())
            self.assertTrue(prompt_new.exists())


    def test_cleanup_skips_files_deleted_between_iterdir_and_stat(self) -> None:
        """Cleanup must not raise FileNotFoundError if a file disappears mid-scan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            StateStore(root / ".codex-loop" / "state.json").create_initial(
                "demo", "Build demo", ["001-foundation"]
            )
            logs_dir = root / ".codex-loop" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            survivor = logs_dir / "0002-survivor.txt"
            survivor.write_text("ok", encoding="utf-8")
            ghost = logs_dir / "0001-ghost.txt"
            ghost.write_text("gone", encoding="utf-8")

            original_stat = Path.stat

            def _stat_that_raises_for_ghost(self_path, *args, **kwargs):
                if self_path == ghost:
                    raise FileNotFoundError("simulated concurrent delete")
                return original_stat(self_path, *args, **kwargs)

            with patch("pathlib.Path.stat", _stat_that_raises_for_ghost):
                report = run_cleanup(root, apply=False, keep=1, remove_worktrees=False)

            # Should not raise and should process the survivor
            all_entries = report.removed + report.kept
            self.assertTrue(
                any("survivor" in e for e in all_entries),
                f"Survivor not in report: {all_entries}",
            )


    def test_cleanup_worktrees_survives_missing_state_json(self) -> None:
        """run_cleanup must not raise when state.json is absent during worktree cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Intentionally do NOT create state.json
            report = run_cleanup(
                root,
                apply=False,
                keep=1,
                remove_worktrees=True,
            )
            # No exception raised; no worktrees to prune anyway
            self.assertIsInstance(report.warnings, list)

    def test_cleanup_worktrees_survives_git_oserror(self) -> None:
        """run_cleanup must record a warning (not raise) when git is unavailable."""
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            StateStore(root / ".codex-loop" / "state.json").create_initial(
                "demo", "Build demo", ["001-foundation"]
            )
            with patch(
                "codex_loop.cleanup.resolve_repo_root",
                side_effect=OSError("git not found"),
            ):
                report = run_cleanup(
                    root,
                    apply=False,
                    keep=1,
                    remove_worktrees=True,
                )
            self.assertTrue(
                any("Skipping worktree cleanup" in w for w in report.warnings),
                f"Expected warning not found: {report.warnings}",
            )


if __name__ == "__main__":
    unittest.main()
