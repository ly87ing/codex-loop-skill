from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any, Callable


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def daemon_paths(project_dir: Path) -> dict[str, Path]:
    loop_dir = project_dir / ".codex-loop"
    return {
        "loop_dir": loop_dir,
        "metadata": loop_dir / "daemon.json",
        "heartbeat": loop_dir / "daemon-heartbeat.json",
        "log": loop_dir / "daemon.log",
    }


def start_daemon(
    project_dir: Path,
    *,
    retry_blocked: bool,
    cycle_sleep_seconds: float,
    max_cycles: int | None,
    popen_cls: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    status = daemon_status(project_dir)
    if status.get("running"):
        msg = f"codex-loop daemon already running (pid={status.get('pid')})."
        raise RuntimeError(msg)

    paths = daemon_paths(project_dir)
    command = [
        sys.executable,
        "-m",
        "codex_loop",
        "run",
        "--project-dir",
        str(project_dir),
        "--continuous",
        "--retry-errors",
        "--cycle-sleep-seconds",
        str(cycle_sleep_seconds),
    ]
    if retry_blocked:
        command.append("--retry-blocked")
    if max_cycles is not None:
        command.extend(["--max-cycles", str(max_cycles)])

    env = dict(os.environ)
    env["CODEX_LOOP_HEARTBEAT_PATH"] = str(paths["heartbeat"])

    paths["loop_dir"].mkdir(parents=True, exist_ok=True)
    with paths["log"].open("a", encoding="utf-8") as log_handle:
        process = popen_cls(
            command,
            cwd=str(project_dir),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )

    metadata = {
        "pid": int(process.pid),
        "started_at": _now(),
        "project_dir": str(project_dir),
        "log_path": str(paths["log"]),
        "heartbeat_path": str(paths["heartbeat"]),
        "command": command,
        "retry_blocked": retry_blocked,
        "cycle_sleep_seconds": cycle_sleep_seconds,
        "max_cycles": max_cycles,
        "heartbeat_stale_seconds": 300,
    }
    _write_json(paths["metadata"], metadata)
    return metadata


def daemon_status(
    project_dir: Path,
    *,
    pid_alive_fn: Callable[[int], bool] = _pid_alive,
) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    paths = daemon_paths(project_dir)
    metadata_path = paths["metadata"]
    if not metadata_path.exists():
        return {
            "running": False,
            "pid": None,
            "project_dir": str(project_dir),
            "log_path": str(paths["log"]),
            "heartbeat_path": str(paths["heartbeat"]),
        }

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    pid = int(metadata.get("pid", -1))
    heartbeat_path = Path(metadata.get("heartbeat_path", paths["heartbeat"]))
    heartbeat = (
        json.loads(heartbeat_path.read_text(encoding="utf-8"))
        if heartbeat_path.exists()
        else {}
    )
    heartbeat_stale_seconds = metadata.get("heartbeat_stale_seconds")
    heartbeat_ts = _parse_timestamp(heartbeat.get("updated_at"))
    stale_heartbeat = False
    if isinstance(heartbeat_stale_seconds, (int, float)) and heartbeat_ts is not None:
        age_seconds = (datetime.now(UTC) - heartbeat_ts).total_seconds()
        stale_heartbeat = age_seconds > float(heartbeat_stale_seconds)
    running = pid_alive_fn(pid)
    return {
        "running": running,
        "pid": pid,
        "project_dir": metadata.get("project_dir", str(project_dir)),
        "started_at": metadata.get("started_at"),
        "log_path": metadata.get("log_path", str(paths["log"])),
        "heartbeat_path": str(heartbeat_path),
        "command": metadata.get("command", []),
        "retry_blocked": metadata.get("retry_blocked", False),
        "cycle_sleep_seconds": metadata.get("cycle_sleep_seconds"),
        "max_cycles": metadata.get("max_cycles"),
        "heartbeat_stale_seconds": heartbeat_stale_seconds,
        "stale_heartbeat": stale_heartbeat,
        "dead_process": not running,
        "phase": heartbeat.get("phase"),
        "cycle": heartbeat.get("cycle"),
        "updated_at": heartbeat.get("updated_at"),
        "outcome": heartbeat.get("outcome"),
        "error_count": heartbeat.get("error_count"),
        "last_error": heartbeat.get("last_error"),
    }


def stop_daemon(
    project_dir: Path,
    *,
    kill_fn: Callable[[int, int], None] = os.kill,
    pid_alive_fn: Callable[[int], bool] = _pid_alive,
) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    paths = daemon_paths(project_dir)
    metadata_path = paths["metadata"]
    if not metadata_path.exists():
        msg = f"No daemon metadata found at {metadata_path}"
        raise RuntimeError(msg)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    pid = int(metadata.get("pid", -1))
    if pid_alive_fn(pid):
        kill_fn(pid, signal.SIGTERM)

    metadata_path.unlink(missing_ok=True)
    return {
        "pid": pid,
        "signal": "SIGTERM",
        "log_path": metadata.get("log_path", str(paths["log"])),
    }


def write_daemon_heartbeat(
    path: Path,
    *,
    phase: str,
    cycle: int,
    outcome: str | None = None,
    error_count: int = 0,
    last_error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "phase": phase,
        "cycle": cycle,
        "updated_at": _now(),
        "error_count": error_count,
    }
    if outcome is not None:
        payload["outcome"] = outcome
    if last_error is not None:
        payload["last_error"] = last_error
    _write_json(path, payload)
