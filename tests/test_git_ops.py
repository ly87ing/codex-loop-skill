from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from codex_loop.git_ops import build_worktree_path, create_worktree, resolve_project_working_directory


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

    def test_create_worktree_reattach_oserror_falls_through_to_fresh(self) -> None:
        # If subprocess.run raises OSError during re-attach (e.g. git not found),
        # create_worktree must fall through to creating a fresh worktree.
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            repo_root.mkdir()

            fresh_worktree = root / "fresh"
            fresh_worktree.mkdir()

            call_count = [0]

            def fake_run(cmd, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    # Re-attach call: raise OSError (e.g. git binary missing).
                    raise OSError("No such file or directory: 'git'")
                # Fresh worktree creation: succeed.
                class _R:
                    returncode = 0
                    stdout = ""
                    stderr = ""
                return _R()

            existing_path = str(root / "nonexistent")
            existing_branch = "codex-loop/old-branch"

            with patch("codex_loop.git_ops.subprocess.run", side_effect=fake_run):
                with patch("codex_loop.git_ops.build_worktree_path", return_value=fresh_worktree):
                    info = create_worktree(
                        repo_root=repo_root,
                        branch_prefix="codex-loop/",
                        task_id="001-task",
                        existing_path=existing_path,
                        existing_branch=existing_branch,
                    )

            # Should have fallen through to fresh worktree creation.
            self.assertEqual(info.path, fresh_worktree)
            self.assertNotEqual(info.branch_name, existing_branch)


if __name__ == "__main__":
    unittest.main()
