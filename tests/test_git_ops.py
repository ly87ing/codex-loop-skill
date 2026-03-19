from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_loop.git_ops import build_worktree_path, resolve_project_working_directory


class GitOpsTests(unittest.TestCase):
    def test_build_worktree_path_uses_hidden_sibling_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "demo"
            repo_root.mkdir()

            path = build_worktree_path(repo_root, "codex-loop/foundation-001")

            self.assertEqual(path.parent.parent.name, ".codex-loop-worktrees")
            self.assertEqual(path.parent.name, "demo")
            self.assertEqual(path.name, "codex-loop-foundation-001")

    def test_resolve_project_working_directory_preserves_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            project_dir = repo_root / "services" / "api"
            worktree_root = root / "worktree" / "repo"
            project_dir.mkdir(parents=True)
            (worktree_root / "services" / "api").mkdir(parents=True)

            resolved = resolve_project_working_directory(
                project_dir=project_dir,
                repo_root=repo_root,
                worktree_root=worktree_root,
            )

            self.assertEqual(resolved, worktree_root / "services" / "api")


if __name__ == "__main__":
    unittest.main()
