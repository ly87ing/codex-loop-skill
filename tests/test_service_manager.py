from __future__ import annotations

from datetime import UTC, datetime
import json
import plistlib
import tempfile
import unittest
from pathlib import Path

from codex_loop.service_manager import (
    install_service,
    service_label,
    service_status,
    uninstall_service,
)


class _CompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeRun:
    def __init__(self, *results: _CompletedProcess) -> None:
        self.calls: list[list[str]] = []
        self._results = list(results) or [_CompletedProcess()]

    def __call__(self, args, **kwargs) -> _CompletedProcess:
        self.calls.append(list(args))
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0]


class ServiceManagerTests(unittest.TestCase):
    def test_install_service_refuses_when_daemon_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            home_dir = Path(tmpdir) / "home"
            root.mkdir(parents=True, exist_ok=True)

            with self.assertRaisesRegex(RuntimeError, "daemon is already running"):
                install_service(
                    root,
                    retry_blocked=True,
                    cycle_sleep_seconds=60.0,
                    max_cycles=None,
                    uid=501,
                    home_dir=home_dir,
                    platform="darwin",
                    daemon_status_fn=lambda project_dir: {"running": True, "pid": 43210},
                )

    def test_install_service_writes_plist_and_bootstraps_launch_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            home_dir = Path(tmpdir) / "home"
            root.mkdir(parents=True, exist_ok=True)
            fake_run = _FakeRun(_CompletedProcess(returncode=0))

            result = install_service(
                root,
                retry_blocked=True,
                cycle_sleep_seconds=60.0,
                max_cycles=None,
                uid=501,
                home_dir=home_dir,
                platform="darwin",
                run_cmd=fake_run,
                daemon_status_fn=lambda project_dir: {"running": False},
            )

            label = service_label(root)
            plist_path = home_dir / "Library" / "LaunchAgents" / f"{label}.plist"
            self.assertTrue(plist_path.exists())
            plist_payload = plistlib.loads(plist_path.read_bytes())
            self.assertEqual(plist_payload["Label"], label)
            self.assertIn("watchdog", plist_payload["ProgramArguments"])
            self.assertIn("--heartbeat-path", plist_payload["ProgramArguments"])
            self.assertIn("--watchdog-state-path", plist_payload["ProgramArguments"])
            self.assertIn("--retry-blocked", plist_payload["ProgramArguments"])
            env = plist_payload["EnvironmentVariables"]
            self.assertEqual(
                env["CODEX_LOOP_HEARTBEAT_PATH"],
                str((root / ".codex-loop" / "service-heartbeat.json").resolve()),
            )
            self.assertIn("PATH", env)
            self.assertEqual(
                fake_run.calls,
                [["launchctl", "bootstrap", "gui/501", str(plist_path.resolve())]],
            )
            self.assertEqual(result["label"], label)
            self.assertEqual(result["plist_path"], str(plist_path.resolve()))
            self.assertEqual(
                result["watchdog_path"],
                str((root / ".codex-loop" / "service-watchdog.json").resolve()),
            )
            self.assertEqual(result["max_restarts"], 10)

    def test_service_status_reports_loaded_heartbeat_and_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            home_dir = Path(tmpdir) / "home"
            root.mkdir(parents=True, exist_ok=True)
            label = service_label(root)
            loop_dir = root / ".codex-loop"
            loop_dir.mkdir(parents=True, exist_ok=True)
            plist_path = home_dir / "Library" / "LaunchAgents" / f"{label}.plist"
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_bytes(plistlib.dumps({"Label": label}))
            (loop_dir / "service.json").write_text(
                json.dumps(
                    {
                        "label": label,
                        "domain": "gui/501",
                        "project_dir": str(root.resolve()),
                        "plist_path": str(plist_path),
                        "log_path": str((loop_dir / "service.log").resolve()),
                        "heartbeat_path": str((loop_dir / "service-heartbeat.json").resolve()),
                        "retry_blocked": True,
                        "cycle_sleep_seconds": 60.0,
                        "max_cycles": None,
                        "heartbeat_stale_seconds": 300,
                    }
                ),
                encoding="utf-8",
            )
            (loop_dir / "service-heartbeat.json").write_text(
                json.dumps(
                    {
                        "phase": "running",
                        "cycle": 4,
                        "updated_at": datetime.now(UTC).isoformat(),
                        "error_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            fake_run = _FakeRun(_CompletedProcess(returncode=0, stdout="service = running"))

            status = service_status(
                root,
                uid=501,
                home_dir=home_dir,
                platform="darwin",
                run_cmd=fake_run,
            )

            self.assertTrue(status["installed"])
            self.assertTrue(status["loaded"])
            self.assertFalse(status["stale_heartbeat"])
            self.assertEqual(status["label"], label)
            self.assertEqual(status["domain"], "gui/501")
            self.assertEqual(status["cycle"], 4)
            self.assertEqual(status["error_count"], 1)
            self.assertEqual(
                fake_run.calls,
                [["launchctl", "print", f"gui/501/{label}"]],
            )

    def test_service_status_marks_missing_heartbeat_when_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            home_dir = Path(tmpdir) / "home"
            root.mkdir(parents=True, exist_ok=True)
            label = service_label(root)
            loop_dir = root / ".codex-loop"
            loop_dir.mkdir(parents=True, exist_ok=True)
            plist_path = home_dir / "Library" / "LaunchAgents" / f"{label}.plist"
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_bytes(plistlib.dumps({"Label": label}))
            (loop_dir / "service.json").write_text(
                json.dumps(
                    {
                        "label": label,
                        "domain": "gui/501",
                        "project_dir": str(root.resolve()),
                        "plist_path": str(plist_path),
                        "log_path": str((loop_dir / "service.log").resolve()),
                        "heartbeat_path": str((loop_dir / "service-heartbeat.json").resolve()),
                        "retry_blocked": True,
                        "cycle_sleep_seconds": 60.0,
                        "max_cycles": None,
                        "heartbeat_stale_seconds": 300,
                    }
                ),
                encoding="utf-8",
            )
            fake_run = _FakeRun(_CompletedProcess(returncode=0, stdout="service = running"))

            status = service_status(
                root,
                uid=501,
                home_dir=home_dir,
                platform="darwin",
                run_cmd=fake_run,
            )

            self.assertTrue(status["installed"])
            self.assertTrue(status["loaded"])
            self.assertTrue(status["missing_heartbeat"])
            self.assertFalse(status["healthy"])
            self.assertIsNone(status["updated_at"])

    def test_uninstall_service_boots_out_and_removes_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            home_dir = Path(tmpdir) / "home"
            root.mkdir(parents=True, exist_ok=True)
            label = service_label(root)
            loop_dir = root / ".codex-loop"
            loop_dir.mkdir(parents=True, exist_ok=True)
            plist_path = home_dir / "Library" / "LaunchAgents" / f"{label}.plist"
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_bytes(plistlib.dumps({"Label": label}))
            metadata_path = loop_dir / "service.json"
            heartbeat_path = loop_dir / "service-heartbeat.json"
            watchdog_path = loop_dir / "service-watchdog.json"
            heartbeat_path.write_text("{}", encoding="utf-8")
            watchdog_path.write_text("{}", encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "label": label,
                        "domain": "gui/501",
                        "project_dir": str(root.resolve()),
                        "plist_path": str(plist_path),
                        "log_path": str((loop_dir / "service.log").resolve()),
                        "heartbeat_path": str(heartbeat_path.resolve()),
                        "watchdog_path": str(watchdog_path.resolve()),
                    }
                ),
                encoding="utf-8",
            )
            fake_run = _FakeRun(
                _CompletedProcess(returncode=0),
                _CompletedProcess(returncode=1, stderr="Could not find service"),
            )

            result = uninstall_service(
                root,
                uid=501,
                home_dir=home_dir,
                platform="darwin",
                run_cmd=fake_run,
                sleep_fn=lambda seconds: None,
            )

            self.assertEqual(
                fake_run.calls,
                [
                    ["launchctl", "bootout", "gui/501", str(plist_path)],
                    ["launchctl", "print", f"gui/501/{label}"],
                ],
            )
            self.assertFalse(plist_path.exists())
            self.assertFalse(metadata_path.exists())
            self.assertFalse(heartbeat_path.exists())
            self.assertFalse(watchdog_path.exists())
            self.assertEqual(result["label"], label)
            self.assertEqual(result["plist_path"], str(plist_path))

    def test_uninstall_service_raises_if_job_stays_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            home_dir = Path(tmpdir) / "home"
            root.mkdir(parents=True, exist_ok=True)
            label = service_label(root)
            loop_dir = root / ".codex-loop"
            loop_dir.mkdir(parents=True, exist_ok=True)
            plist_path = home_dir / "Library" / "LaunchAgents" / f"{label}.plist"
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_bytes(plistlib.dumps({"Label": label}))
            metadata_path = loop_dir / "service.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "label": label,
                        "domain": "gui/501",
                        "project_dir": str(root.resolve()),
                        "plist_path": str(plist_path),
                        "log_path": str((loop_dir / "service.log").resolve()),
                        "heartbeat_path": str((loop_dir / "service-heartbeat.json").resolve()),
                        "watchdog_path": str((loop_dir / "service-watchdog.json").resolve()),
                    }
                ),
                encoding="utf-8",
            )
            fake_run = _FakeRun(
                _CompletedProcess(returncode=0),
                _CompletedProcess(returncode=0, stdout="still loaded"),
            )

            with self.assertRaisesRegex(RuntimeError, "still loaded"):
                uninstall_service(
                    root,
                    uid=501,
                    home_dir=home_dir,
                    platform="darwin",
                    run_cmd=fake_run,
                    sleep_fn=lambda seconds: None,
                    wait_timeout_seconds=0.0,
                )

            self.assertTrue(plist_path.exists())
            self.assertTrue(metadata_path.exists())


    def test_service_status_handles_corrupt_metadata_gracefully(self) -> None:
        """service_status returns sane defaults when service.json is corrupt JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            home_dir = Path(tmpdir) / "home"
            root.mkdir(parents=True, exist_ok=True)
            loop_dir = root / ".codex-loop"
            loop_dir.mkdir(parents=True, exist_ok=True)
            (loop_dir / "service.json").write_text("{bad json", encoding="utf-8")

            status = service_status(
                root,
                uid=501,
                home_dir=home_dir,
                platform="darwin",
                run_cmd=lambda *a, **kw: type(
                    "R", (), {"returncode": 1, "stdout": "", "stderr": ""}
                )(),
            )

            self.assertFalse(status["loaded"])
            self.assertFalse(status["healthy"])
            self.assertIsNotNone(status["label"])


if __name__ == "__main__":
    unittest.main()
