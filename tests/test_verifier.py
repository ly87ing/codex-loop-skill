from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_loop.verifier import Verifier


class VerifierTests(unittest.TestCase):
    def test_empty_command_list_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, results = Verifier().run([], Path(tmpdir))

            self.assertFalse(ok)
            self.assertEqual(results[0]["exit_code"], 1)

    def test_pass_requires_all_false_allows_any_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, results = Verifier().run(
                ["python3 -c 'raise SystemExit(1)'", "python3 -c 'print(1)'"],
                Path(tmpdir),
                pass_requires_all=False,
            )

            self.assertTrue(ok)
            self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
