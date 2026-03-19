from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_loop.git_ops import build_worktree_path


class GitOpsTests(unittest.TestCase):
    def test_build_worktree_path_uses_hidden_sibling_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "demo"
            repo_root.mkdir()

            path = build_worktree_path(repo_root, "codex-loop/foundation-001")

            self.assertEqual(path.parent.parent.name, ".codex-loop-worktrees")
            self.assertEqual(path.parent.name, "demo")
            self.assertEqual(path.name, "codex-loop-foundation-001")


if __name__ == "__main__":
    unittest.main()

