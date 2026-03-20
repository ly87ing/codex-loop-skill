from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Callable
from .state_store import StateStore


DEFAULT_STALE_AFTER_SECONDS = 300.0
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_RESTART_BACKOFF_SECONDS = 5.0
DEFAULT_TERMINATE_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RESTARTS = 10


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def build_worker_command(
    project_dir: Path,
    *,
    heartbeat_path: Path,
    retry_blocked: bool,
    cycle_sleep_seconds: float,
    max_cycles: int | None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "codex_loop",
        "run",
        "--project-dir",
        str(project_dir.resolve()),
        "--continuous",
        "--retry-errors",
        "--heartbeat-path",
        str(heartbeat_path.resolve()),
        "--cycle-sleep-seconds",
        str(cycle_sleep_seconds),
    ]
    if retry_blocked:
        command.append("--retry-blocked")
    if max_cycles is not None:
        command.extend(["--max-cycles", str(max_cycles)])
    return command


def build_watchdog_command(
    project_dir: Path,
    *,
    heartbeat_path: Path,
    watchdog_state_path: Path,
    retry_blocked: bool,
    cycle_sleep_seconds: float,
    max_cycles: int | None,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    restart_backoff_seconds: float = DEFAULT_RESTART_BACKOFF_SECONDS,
    terminate_timeout_seconds: float = DEFAULT_TERMINATE_TIMEOUT_SECONDS,
    max_restarts: int | None = DEFAULT_MAX_RESTARTS,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "codex_loop",
        "watchdog",
        "--project-dir",
        str(project_dir.resolve()),
        "--heartbeat-path",
        str(heartbeat_path.resolve()),
        "--watchdog-state-path",
        str(watchdog_state_path.resolve()),
        "--stale-after-seconds",
        str(stale_after_seconds),
        "--poll-interval-seconds",
        str(poll_interval_seconds),
        "--restart-backoff-seconds",
        str(restart_backoff_seconds),
        "--terminate-timeout-seconds",
        str(terminate_timeout_seconds),
        "--cycle-sleep-seconds",
        str(cycle_sleep_seconds),
    ]
    if retry_blocked:
        command.append("--retry-blocked")
    if max_cycles is not None:
        command.extend(["--max-cycles", str(max_cycles)])
    if max_restarts is not None:
        command.extend(["--max-restarts", str(max_restarts)])
    return command


def _write_watchdog_state(
    path: Path,
    *,
    phase: str,
    child_pid: int | None,
    restart_count: int,
    last_restart_reason: str | None = None,
    child_exit_code: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "watchdog_pid": os.getpid(),
        "phase": phase,
        "child_pid": child_pid,
        "restart_count": restart_count,
        "updated_at": _now(),
    }
    if last_restart_reason is not None:
        payload["last_restart_reason"] = last_restart_reason
    if child_exit_code is not None:
        payload["child_exit_code"] = child_exit_code
    try:
        _write_json(path, payload)
    except OSError:
        pass  # Watchdog state is observability data; I/O failure must not crash the loop


def _read_heartbeat(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _heartbeat_is_stale(
    *,
    heartbeat_path: Path,
    child_started_at: datetime,
    stale_after_seconds: float,
    now: datetime,
) -> bool:
    heartbeat = _read_heartbeat(heartbeat_path)
    if not heartbeat_path.exists():
        return (now - child_started_at).total_seconds() > stale_after_seconds
    heartbeat_ts = _parse_timestamp(heartbeat.get("updated_at"))
    if heartbeat_ts is None:
        return (now - child_started_at).total_seconds() > stale_after_seconds
    return (now - heartbeat_ts).total_seconds() > stale_after_seconds


def _terminate_process(process: Any, *, timeout_seconds: float) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            pass  # Process is unkillable; abandon and continue


def run_watchdog(
    project_dir: Path,
    *,
    heartbeat_path: Path,
    watchdog_state_path: Path,
    retry_blocked: bool,
    cycle_sleep_seconds: float,
    max_cycles: int | None,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    restart_backoff_seconds: float = DEFAULT_RESTART_BACKOFF_SECONDS,
    terminate_timeout_seconds: float = DEFAULT_TERMINATE_TIMEOUT_SECONDS,
    max_restarts: int | None = None,
    worker_factory: Callable[..., Any] = subprocess.Popen,
    sleep_fn: Callable[[float], None] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> int:
    project_dir = project_dir.resolve()
    heartbeat_path = heartbeat_path.resolve()
    watchdog_state_path = watchdog_state_path.resolve()
    state_store = StateStore(project_dir / ".codex-loop" / "state.json")
    try:
        state_store.ensure_initialized(
            project_name=project_dir.name,
            source_prompt="Watchdog runtime state",
        )
    except OSError:
        pass  # State init failure must not abort the watchdog; _safe_record handles subsequent I/O errors
    sleep = sleep_fn or time.sleep
    now = now_fn or (lambda: datetime.now(UTC))

    def _safe_record(**kwargs: Any) -> None:
        """Record a watchdog event, ignoring I/O errors so the loop survives
        state.json write failures (e.g. disk full)."""
        try:
            state_store.record_watchdog_event(**kwargs)
        except Exception:  # noqa: BLE001
            pass

    stop_requested = False
    current_process: Any | None = None
    restart_count = 0
    last_restart_reason: str | None = None
    child_started_at = now()

    def spawn_worker() -> Any:
        heartbeat_path.unlink(missing_ok=True)
        command = build_worker_command(
            project_dir,
            heartbeat_path=heartbeat_path,
            retry_blocked=retry_blocked,
            cycle_sleep_seconds=cycle_sleep_seconds,
            max_cycles=max_cycles,
        )
        env = dict(os.environ)
        env["CODEX_LOOP_HEARTBEAT_PATH"] = str(heartbeat_path)
        process = worker_factory(
            command,
            cwd=str(project_dir),
            env=env,
            stdin=subprocess.DEVNULL,
        )
        return process

    def request_stop(signum, frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        if current_process is not None:
            _terminate_process(current_process, timeout_seconds=terminate_timeout_seconds)

    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    try:
        try:
            current_process = spawn_worker()
        except OSError as spawn_exc:
            _write_watchdog_state(
                watchdog_state_path,
                phase="spawn_failed",
                child_pid=None,
                restart_count=restart_count,
                last_restart_reason=f"spawn_failed:{spawn_exc}",
            )
            return 1
        child_started_at = now()
        _write_watchdog_state(
            watchdog_state_path,
            phase="running",
            child_pid=current_process.pid,
            restart_count=restart_count,
        )
        while True:
            if stop_requested:
                _write_watchdog_state(
                    watchdog_state_path,
                    phase="stopped",
                    child_pid=getattr(current_process, "pid", None),
                    restart_count=restart_count,
                    last_restart_reason=last_restart_reason,
                )
                return 0

            exit_code = current_process.poll()
            if exit_code is not None:
                if exit_code == 0:
                    _write_watchdog_state(
                        watchdog_state_path,
                        phase="completed",
                        child_pid=current_process.pid,
                        restart_count=restart_count,
                        last_restart_reason=last_restart_reason,
                        child_exit_code=exit_code,
                    )
                    return 0
                if max_restarts is not None and restart_count >= max_restarts:
                    _write_watchdog_state(
                        watchdog_state_path,
                        phase="exhausted",
                        child_pid=current_process.pid,
                        restart_count=restart_count,
                        last_restart_reason=last_restart_reason,
                        child_exit_code=exit_code,
                    )
                    _safe_record(
                        event_type="watchdog_exhausted",
                        summary="Watchdog exhausted restart budget after worker exit.",
                        restart_reason=last_restart_reason or f"exit_code:{exit_code}",
                        restart_count=restart_count,
                        child_pid=current_process.pid,
                        child_exit_code=exit_code,
                        watchdog_phase="exhausted",
                    )
                    return exit_code
                restart_count += 1
                last_restart_reason = f"exit_code:{exit_code}"
                _write_watchdog_state(
                    watchdog_state_path,
                    phase="restarting",
                    child_pid=current_process.pid,
                    restart_count=restart_count,
                    last_restart_reason=last_restart_reason,
                    child_exit_code=exit_code,
                )
                _safe_record(
                    event_type="watchdog_restart",
                    summary="Restarting worker after non-zero exit.",
                    restart_reason=last_restart_reason,
                    restart_count=restart_count,
                    child_pid=current_process.pid,
                    child_exit_code=exit_code,
                    watchdog_phase="restarting",
                )
                sleep(restart_backoff_seconds)
                try:
                    current_process = spawn_worker()
                except OSError as spawn_exc:
                    _write_watchdog_state(
                        watchdog_state_path,
                        phase="spawn_failed",
                        child_pid=None,
                        restart_count=restart_count,
                        last_restart_reason=f"spawn_failed:{spawn_exc}",
                    )
                    sleep(restart_backoff_seconds)
                    continue
                child_started_at = now()
                _write_watchdog_state(
                    watchdog_state_path,
                    phase="running",
                    child_pid=current_process.pid,
                    restart_count=restart_count,
                    last_restart_reason=last_restart_reason,
                )
                continue

            if _heartbeat_is_stale(
                heartbeat_path=heartbeat_path,
                child_started_at=child_started_at,
                stale_after_seconds=stale_after_seconds,
                now=now(),
            ):
                _terminate_process(current_process, timeout_seconds=terminate_timeout_seconds)
                if max_restarts is not None and restart_count >= max_restarts:
                    _write_watchdog_state(
                        watchdog_state_path,
                        phase="exhausted",
                        child_pid=current_process.pid,
                        restart_count=restart_count,
                        last_restart_reason="stale_heartbeat",
                    )
                    _safe_record(
                        event_type="watchdog_exhausted",
                        summary="Watchdog exhausted restart budget after stale heartbeat.",
                        restart_reason="stale_heartbeat",
                        restart_count=restart_count,
                        child_pid=current_process.pid,
                        watchdog_phase="exhausted",
                    )
                    return 1
                restart_count += 1
                last_restart_reason = "stale_heartbeat"
                _write_watchdog_state(
                    watchdog_state_path,
                    phase="restarting",
                    child_pid=current_process.pid,
                    restart_count=restart_count,
                    last_restart_reason=last_restart_reason,
                )
                _safe_record(
                    event_type="watchdog_restart",
                    summary="Restarting worker after stale heartbeat.",
                    restart_reason=last_restart_reason,
                    restart_count=restart_count,
                    child_pid=current_process.pid,
                    watchdog_phase="restarting",
                )
                sleep(restart_backoff_seconds)
                try:
                    current_process = spawn_worker()
                except OSError as spawn_exc:
                    _write_watchdog_state(
                        watchdog_state_path,
                        phase="spawn_failed",
                        child_pid=None,
                        restart_count=restart_count,
                        last_restart_reason=f"spawn_failed:{spawn_exc}",
                    )
                    sleep(restart_backoff_seconds)
                    continue
                child_started_at = now()
                _write_watchdog_state(
                    watchdog_state_path,
                    phase="running",
                    child_pid=current_process.pid,
                    restart_count=restart_count,
                    last_restart_reason=last_restart_reason,
                )
                continue

            _write_watchdog_state(
                watchdog_state_path,
                phase="running",
                child_pid=current_process.pid,
                restart_count=restart_count,
                last_restart_reason=last_restart_reason,
            )
            sleep(poll_interval_seconds)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)
