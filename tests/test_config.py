from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_loop.config import CodexLoopConfig


class ConfigTests(unittest.TestCase):
    def test_rejects_empty_verification_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "verification": {"commands": []},
                    },
                    root,
                )

    def test_rejects_non_positive_iteration_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "execution": {
                            "max_iterations": 0,
                            "max_no_progress_iterations": 0,
                        },
                        "verification": {"commands": ["python -m unittest"]},
                    },
                    root,
                )

    def test_rejects_unsupported_task_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                        "tasks": {"strategy": "parallel"},
                    },
                    root,
                )


if __name__ == "__main__":
    unittest.main()

