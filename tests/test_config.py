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

    def test_rejects_invalid_timeout_and_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "execution": {"iteration_timeout_seconds": 0},
                        "verification": {"commands": ["python -m unittest"]},
                    },
                    root,
                )
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "execution": {"iteration_backoff_jitter_seconds": -0.1},
                        "verification": {"commands": ["python -m unittest"]},
                    },
                    root,
                )

    def test_rejects_negative_circuit_breaker_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "execution": {"max_consecutive_runner_failures": -1},
                        "verification": {"commands": ["python -m unittest"]},
                    },
                    root,
                )

    def test_rejects_unsupported_hook_failure_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                        "hooks": {"failure_policy": "explode"},
                    },
                    root,
                )
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "execution": {"max_consecutive_verification_failures": -1},
                        "verification": {"commands": ["python -m unittest"]},
                    },
                    root,
                )
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "execution": {"iteration_backoff_seconds": -1},
                        "verification": {"commands": ["python -m unittest"]},
                    },
                    root,
                )

    def test_parses_operator_cleanup_and_events_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = CodexLoopConfig.from_dict(
                {
                    "project": {"name": "demo"},
                    "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                    "verification": {"commands": ["python -m unittest"]},
                    "operator": {
                        "events": {"default_limit": 50},
                        "cleanup": {
                            "keep": 7,
                            "older_than_days": 14,
                            "directory_keep": {"logs": 20},
                            "directory_older_than_days": {"prompts": 30},
                        },
                    },
                },
                root,
            )

            self.assertEqual(config.operator.events.default_limit, 50)
            self.assertEqual(config.operator.cleanup.keep, 7)
            self.assertEqual(config.operator.cleanup.older_than_days, 14)
            self.assertEqual(config.operator.cleanup.directory_keep["logs"], 20)
            self.assertEqual(
                config.operator.cleanup.directory_older_than_days["prompts"], 30
            )

    def test_rejects_invalid_operator_cleanup_directory_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                        "operator": {
                            "events": {"default_limit": 0},
                        },
                    },
                    root,
                )
            with self.assertRaises(ValueError):
                CodexLoopConfig.from_dict(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                        "operator": {
                            "cleanup": {
                                "directory_keep": {"artifacts": 3},
                            },
                        },
                    },
                    root,
                )


if __name__ == "__main__":
    unittest.main()
