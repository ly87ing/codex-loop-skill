from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_loop.verifier import Verifier


class VerifierTests(unittest.TestCase):
    def test_empty_command_list_passes(self) -> None:
        # Empty commands means "no verification" — treat as auto-pass.
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, results = Verifier().run([], Path(tmpdir))

            self.assertTrue(ok)
            self.assertEqual(results, [])

    def test_pass_requires_all_false_allows_any_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, results = Verifier().run(
                ["python3 -c 'raise SystemExit(1)'", "python3 -c 'print(1)'"],
                Path(tmpdir),
                pass_requires_all=False,
            )

            self.assertTrue(ok)
            self.assertEqual(len(results), 2)


    def test_timed_out_command_counts_as_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, results = Verifier().run(
                ["python3 -c 'import time; time.sleep(10)'"],
                Path(tmpdir),
                timeout_seconds=1,
            )

            self.assertFalse(ok)
            self.assertTrue(results[0]["timed_out"])
            self.assertIsNone(results[0]["exit_code"])

    def test_timeout_result_includes_timed_out_false_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, results = Verifier().run(
                ["python3 -c 'print(1)'"],
                Path(tmpdir),
                timeout_seconds=30,
            )

            self.assertTrue(ok)
            self.assertFalse(results[0]["timed_out"])


    def test_oserror_on_bad_cwd_counts_as_failure(self) -> None:
        # subprocess.run raises OSError when cwd does not exist; Verifier
        # must catch it and treat it as a failed command rather than crashing.
        ok, results = Verifier().run(
            ["echo hi"],
            Path("/nonexistent/path/that/does/not/exist"),
        )

        self.assertFalse(ok)
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["exit_code"])
        self.assertFalse(results[0]["timed_out"])
        self.assertIn("nonexistent", results[0]["stderr"].lower() + results[0]["command"].lower())


if __name__ == "__main__":
    unittest.main()
