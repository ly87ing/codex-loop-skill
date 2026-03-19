from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.cli import main
from codex_loop.state_store import StateStore


class CliTests(unittest.TestCase):
    def test_status_summary_prints_current_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "codex-loop.yaml").write_text(
                json.dumps(
                    {
                        "project": {"name": "demo"},
                        "goal": {"summary": "Build demo", "done_when": ["Tests pass"]},
                        "verification": {"commands": ["python -m unittest"]},
                    }
                ),
                encoding="utf-8",
            )
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["status", "--project-dir", str(root), "--summary"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("demo", stdout.getvalue())
            self.assertIn("001-foundation", stdout.getvalue())

    def test_logs_tail_prints_latest_log_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs_dir = root / ".codex-loop" / "logs"
            logs_dir.mkdir(parents=True)
            (logs_dir / "0001-first.jsonl").write_text("old\nline\n", encoding="utf-8")
            (logs_dir / "0002-second.jsonl").write_text(
                "one\ntwo\nthree\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    ["logs", "tail", "--project-dir", str(root), "--lines", "2"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(stdout.getvalue().strip().splitlines(), ["two", "three"])


if __name__ == "__main__":
    unittest.main()
