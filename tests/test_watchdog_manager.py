from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.watchdog_manager import run_watchdog


class _FakeProcess:
    def __init__(self, pid: int, polls: list[int | None]) -> None:
        self.pid = pid
        self._polls = list(polls)
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        if len(self._polls) > 1:
            return self._polls.pop(0)
        return self._polls[0]

    def terminate(self) -> None:
        self.terminated = True
        self._polls = [0]

    def kill(self) -> None:
        self.killed = True
        self._polls = [0]

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        return 0


class WatchdogManagerTests(unittest.TestCase):
    def test_run_watchdog_stops_after_max_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            heartbeat_path = root / "heartbeat.json"
            state_path = root / "watchdog.json"
            process = _FakeProcess(3001, [3])

            exit_code = run_watchdog(
                root,
                heartbeat_path=heartbeat_path,
                watchdog_state_path=state_path,
                retry_blocked=False,
                cycle_sleep_seconds=60.0,
                max_cycles=None,
                poll_interval_seconds=0.0,
                restart_backoff_seconds=0.0,
                max_restarts=0,
                worker_factory=lambda args, **kwargs: process,
                sleep_fn=lambda seconds: None,
                now_fn=lambda: datetime(2026, 3, 19, tzinfo=UTC),
            )

            self.assertEqual(exit_code, 3)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["phase"], "exhausted")
            self.assertEqual(state["restart_count"], 0)
            self.assertEqual(state["child_exit_code"], 3)

    def test_run_watchdog_restarts_stale_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            heartbeat_path = root / "heartbeat.json"
            state_path = root / "watchdog.json"
            stale_ts = (datetime(2026, 3, 19, tzinfo=UTC) - timedelta(seconds=10)).isoformat()
            fresh_ts = datetime(2026, 3, 19, tzinfo=UTC).isoformat()
            first = _FakeProcess(1001, [None, None, None])
            second = _FakeProcess(1002, [0])
            processes = [first, second]

            def worker_factory(args, **kwargs):
                process = processes.pop(0)
                if process.pid == 1001:
                    heartbeat_path.write_text(
                        json.dumps({"updated_at": stale_ts, "phase": "running", "cycle": 1}),
                        encoding="utf-8",
                    )
                else:
                    heartbeat_path.write_text(
                        json.dumps({"updated_at": fresh_ts, "phase": "running", "cycle": 2}),
                        encoding="utf-8",
                    )
                return process

            exit_code = run_watchdog(
                root,
                heartbeat_path=heartbeat_path,
                watchdog_state_path=state_path,
                retry_blocked=True,
                cycle_sleep_seconds=60.0,
                max_cycles=None,
                stale_after_seconds=1.0,
                poll_interval_seconds=0.0,
                restart_backoff_seconds=0.0,
                worker_factory=worker_factory,
                sleep_fn=lambda seconds: None,
                now_fn=lambda: datetime(2026, 3, 19, tzinfo=UTC),
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(first.terminated)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["restart_count"], 1)
            self.assertEqual(state["last_restart_reason"], "stale_heartbeat")
            self.assertEqual(state["child_pid"], 1002)
            run_state = json.loads((root / ".codex-loop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(run_state["history"][0]["event_type"], "watchdog_restart")
            self.assertEqual(run_state["history"][0]["restart_reason"], "stale_heartbeat")

    def test_run_watchdog_restarts_worker_after_non_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            heartbeat_path = root / "heartbeat.json"
            state_path = root / "watchdog.json"
            ts = datetime(2026, 3, 19, tzinfo=UTC).isoformat()
            first = _FakeProcess(2001, [2])
            second = _FakeProcess(2002, [0])
            processes = [first, second]

            def worker_factory(args, **kwargs):
                process = processes.pop(0)
                heartbeat_path.write_text(
                    json.dumps({"updated_at": ts, "phase": "running", "cycle": process.pid}),
                    encoding="utf-8",
                )
                return process

            exit_code = run_watchdog(
                root,
                heartbeat_path=heartbeat_path,
                watchdog_state_path=state_path,
                retry_blocked=False,
                cycle_sleep_seconds=60.0,
                max_cycles=None,
                stale_after_seconds=30.0,
                poll_interval_seconds=0.0,
                restart_backoff_seconds=0.0,
                worker_factory=worker_factory,
                sleep_fn=lambda seconds: None,
                now_fn=lambda: datetime(2026, 3, 19, tzinfo=UTC),
            )

            self.assertEqual(exit_code, 0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["restart_count"], 1)
            self.assertEqual(state["last_restart_reason"], "exit_code:2")
            self.assertEqual(state["child_pid"], 2002)
            run_state = json.loads((root / ".codex-loop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(run_state["history"][0]["event_type"], "watchdog_restart")
            self.assertEqual(run_state["history"][0]["restart_reason"], "exit_code:2")

    def test_run_watchdog_records_exhausted_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            heartbeat_path = root / "heartbeat.json"
            state_path = root / "watchdog.json"
            process = _FakeProcess(3001, [3])

            exit_code = run_watchdog(
                root,
                heartbeat_path=heartbeat_path,
                watchdog_state_path=state_path,
                retry_blocked=False,
                cycle_sleep_seconds=60.0,
                max_cycles=None,
                poll_interval_seconds=0.0,
                restart_backoff_seconds=0.0,
                max_restarts=0,
                worker_factory=lambda args, **kwargs: process,
                sleep_fn=lambda seconds: None,
                now_fn=lambda: datetime(2026, 3, 19, tzinfo=UTC),
            )

            self.assertEqual(exit_code, 3)
            run_state = json.loads((root / ".codex-loop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(run_state["history"][0]["event_type"], "watchdog_exhausted")
            self.assertEqual(run_state["history"][0]["restart_reason"], "exit_code:3")
            self.assertEqual(run_state["history"][0]["child_exit_code"], 3)


    def test_run_watchdog_survives_spawn_oserror_on_restart(self) -> None:
        """If spawn_worker raises OSError during a restart, watchdog records
        spawn_failed state and retries rather than crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            heartbeat_path = root / "heartbeat.json"
            state_path = root / "watchdog.json"

            call_count = 0

            # First call: returns a process that exits with code 1 (triggers restart).
            # Second call: raises OSError (spawn failure).
            # Third call: returns a process that exits with code 0 (success).
            first = _FakeProcess(1001, [1])
            third = _FakeProcess(1003, [0])

            def worker_factory(args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return first
                if call_count == 2:
                    raise OSError("No such file or directory")
                return third

            exit_code = run_watchdog(
                root,
                heartbeat_path=heartbeat_path,
                watchdog_state_path=state_path,
                retry_blocked=False,
                cycle_sleep_seconds=60.0,
                max_cycles=None,
                poll_interval_seconds=0.0,
                restart_backoff_seconds=0.0,
                max_restarts=5,
                worker_factory=worker_factory,
                sleep_fn=lambda seconds: None,
                now_fn=lambda: datetime(2026, 3, 19, tzinfo=UTC),
            )

            self.assertEqual(exit_code, 0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["phase"], "completed")
            self.assertEqual(call_count, 3)


if __name__ == "__main__":
    unittest.main()
