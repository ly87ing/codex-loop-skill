from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
