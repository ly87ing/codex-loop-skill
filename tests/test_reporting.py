from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.reporting import format_events_timeline
from codex_loop.state_store import StateStore


class ReportingTests(unittest.TestCase):
    def test_events_timeline_includes_hook_and_blocked_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            hooks_dir = root / ".codex-loop" / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            (hooks_dir / "post_iteration.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-19T00:00:00+00:00",
                        "command": "echo hi",
                        "success": True,
                        "exit_code": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rendered = format_events_timeline(root, limit=10)

            self.assertIn("runner_failure", rendered)
            self.assertIn("hook:post_iteration", rendered)
            self.assertIn("blocked:no_progress_limit", rendered)


if __name__ == "__main__":
    unittest.main()
