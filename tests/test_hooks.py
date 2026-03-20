from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_loop.hooks import HookRunner


class HookRunnerTests(unittest.TestCase):
    def test_run_one_oserror_returns_failure_result(self) -> None:
        # subprocess.run raises OSError when cwd does not exist; _run_one must
        # catch it and return a failure dict rather than propagating.
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = HookRunner(Path(tmpdir) / "hooks")
            results = runner.run(
                event_name="pre_iteration",
                commands=["echo hi"],
                cwd=Path("/nonexistent/path/that/does/not/exist"),
                timeout_seconds=10,
            )

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["success"])
        self.assertIsNone(results[0]["exit_code"])
        self.assertFalse(results[0]["timed_out"])
        self.assertNotEqual(results[0]["stderr"], "")

    def test_run_survives_log_dir_mkdir_oserror(self) -> None:
        # If log_dir.mkdir raises OSError (e.g. read-only filesystem), run()
        # must still execute commands and return results.
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = HookRunner(Path(tmpdir) / "hooks")
            with patch.object(Path, "mkdir", side_effect=OSError("read-only")):
                results = runner.run(
                    event_name="pre_iteration",
                    commands=["python3 -c 'print(1)'"],
                    cwd=Path(tmpdir),
                    timeout_seconds=10,
                )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])

    def test_run_returns_empty_for_no_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = HookRunner(Path(tmpdir) / "hooks")
            results = runner.run(
                event_name="pre_iteration",
                commands=[],
                cwd=Path(tmpdir),
                timeout_seconds=10,
            )

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
