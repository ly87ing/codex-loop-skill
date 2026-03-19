from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.daemon_manager import daemon_status, start_daemon, stop_daemon


class _FakePopen:
    def __init__(self, args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.pid = 43210


class DaemonManagerTests(unittest.TestCase):
    def test_start_daemon_refuses_when_service_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with self.assertRaisesRegex(RuntimeError, "service is already loaded"):
                start_daemon(
                    root,
                    retry_blocked=True,
                    cycle_sleep_seconds=45.0,
                    max_cycles=7,
                    popen_cls=_FakePopen,
                    service_status_fn=lambda project_dir: {
                        "loaded": True,
                        "label": "com.codex-loop.demo",
                    },
                )

    def test_start_daemon_writes_metadata_and_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            result = start_daemon(
                root,
                retry_blocked=True,
                cycle_sleep_seconds=45.0,
                max_cycles=7,
                popen_cls=_FakePopen,
                service_status_fn=lambda project_dir: {"loaded": False},
            )

            metadata_path = root / ".codex-loop" / "daemon.json"
            self.assertTrue(metadata_path.exists())
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["pid"], 43210)
            self.assertTrue(metadata["retry_blocked"])
            self.assertEqual(metadata["cycle_sleep_seconds"], 45.0)
            self.assertEqual(metadata["max_cycles"], 7)
            self.assertIn("run", metadata["command"])
            self.assertIn("--retry-errors", metadata["command"])
            self.assertEqual(result["pid"], 43210)
            self.assertEqual(result["log_path"], metadata["log_path"])

    def test_daemon_status_reads_metadata_and_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            loop_dir = root / ".codex-loop"
            loop_dir.mkdir(parents=True, exist_ok=True)
            (loop_dir / "daemon.json").write_text(
                json.dumps(
                    {
                        "pid": 43210,
                        "started_at": "2026-03-19T00:00:00+00:00",
                        "log_path": str(loop_dir / "daemon.log"),
                        "heartbeat_path": str(loop_dir / "daemon-heartbeat.json"),
                        "command": ["python3", "-m", "codex_loop", "run"],
                        "retry_blocked": True,
                        "cycle_sleep_seconds": 60.0,
                        "max_cycles": None,
                    }
                ),
                encoding="utf-8",
            )
            (loop_dir / "daemon-heartbeat.json").write_text(
                json.dumps(
                    {
                        "pid": 43210,
                        "phase": "running",
                        "cycle": 3,
                        "updated_at": "2026-03-19T00:05:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            status = daemon_status(root, pid_alive_fn=lambda pid: pid == 43210)

            self.assertTrue(status["running"])
            self.assertEqual(status["pid"], 43210)
            self.assertEqual(status["phase"], "running")
            self.assertEqual(status["cycle"], 3)

    def test_stop_daemon_signals_process_and_removes_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            loop_dir = root / ".codex-loop"
            loop_dir.mkdir(parents=True, exist_ok=True)
            metadata_path = loop_dir / "daemon.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "pid": 43210,
                        "started_at": "2026-03-19T00:00:00+00:00",
                        "log_path": str(loop_dir / "daemon.log"),
                        "heartbeat_path": str(loop_dir / "daemon-heartbeat.json"),
                        "command": ["python3", "-m", "codex_loop", "run"],
                        "retry_blocked": True,
                        "cycle_sleep_seconds": 60.0,
                        "max_cycles": None,
                    }
                ),
                encoding="utf-8",
            )
            signalled: list[tuple[int, int]] = []

            result = stop_daemon(
                root,
                kill_fn=lambda pid, sig: signalled.append((pid, sig)),
                pid_alive_fn=lambda pid: pid == 43210,
            )

            self.assertEqual(signalled, [(43210, 15)])
            self.assertFalse(metadata_path.exists())
            self.assertEqual(result["pid"], 43210)
            self.assertEqual(result["signal"], "SIGTERM")

    def test_daemon_status_marks_stale_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            loop_dir = root / ".codex-loop"
            loop_dir.mkdir(parents=True, exist_ok=True)
            updated_at = (datetime.now(UTC) - timedelta(seconds=301)).isoformat()
            (loop_dir / "daemon.json").write_text(
                json.dumps(
                    {
                        "pid": 43210,
                        "started_at": "2026-03-19T00:00:00+00:00",
                        "log_path": str(loop_dir / "daemon.log"),
                        "heartbeat_path": str(loop_dir / "daemon-heartbeat.json"),
                        "command": ["python3", "-m", "codex_loop", "run"],
                        "retry_blocked": True,
                        "cycle_sleep_seconds": 60.0,
                        "max_cycles": None,
                        "heartbeat_stale_seconds": 300,
                    }
                ),
                encoding="utf-8",
            )
            (loop_dir / "daemon-heartbeat.json").write_text(
                json.dumps(
                    {
                        "pid": 43210,
                        "phase": "running",
                        "cycle": 3,
                        "updated_at": updated_at,
                    }
                ),
                encoding="utf-8",
            )

            status = daemon_status(root, pid_alive_fn=lambda pid: pid == 43210)

            self.assertTrue(status["running"])
            self.assertTrue(status["stale_heartbeat"])
            self.assertEqual(status["heartbeat_stale_seconds"], 300)

    def test_daemon_status_marks_dead_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            loop_dir = root / ".codex-loop"
            loop_dir.mkdir(parents=True, exist_ok=True)
            (loop_dir / "daemon.json").write_text(
                json.dumps(
                    {
                        "pid": 43210,
                        "started_at": "2026-03-19T00:00:00+00:00",
                        "log_path": str(loop_dir / "daemon.log"),
                        "heartbeat_path": str(loop_dir / "daemon-heartbeat.json"),
                        "command": ["python3", "-m", "codex_loop", "run"],
                        "retry_blocked": True,
                        "cycle_sleep_seconds": 60.0,
                        "max_cycles": None,
                    }
                ),
                encoding="utf-8",
            )

            status = daemon_status(root, pid_alive_fn=lambda pid: False)

            self.assertFalse(status["running"])
            self.assertTrue(status["dead_process"])


if __name__ == "__main__":
    unittest.main()
