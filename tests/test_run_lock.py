from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.run_lock import RunLock


class RunLockTests(unittest.TestCase):
    def test_prevents_second_live_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / ".codex-loop" / "run.lock"
            with RunLock(lock_path, stale_seconds=3600):
                with self.assertRaises(RuntimeError):
                    with RunLock(lock_path, stale_seconds=3600):
                        pass

    def test_recovers_stale_lock_for_dead_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / ".codex-loop" / "run.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text(
                json.dumps(
                    {
                        "pid": 999999,
                        "started_at": "2000-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            with RunLock(lock_path, stale_seconds=3600):
                data = json.loads(lock_path.read_text(encoding="utf-8"))
                self.assertNotEqual(data["pid"], 999999)


if __name__ == "__main__":
    unittest.main()
