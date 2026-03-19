from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
from typing import Any, Callable

from .daemon_manager import _parse_timestamp, _write_json


DEFAULT_HEARTBEAT_STALE_SECONDS = 300


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _require_darwin(platform: str) -> None:
    if platform != "darwin":
        raise RuntimeError("launchd service management is only supported on macOS.")


def _domain_for_uid(uid: int | None) -> str:
    return f"gui/{os.getuid() if uid is None else uid}"


def _sanitize_name(value: str) -> str:
    sanitized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return sanitized or "project"


def service_label(project_dir: Path) -> str:
    project_dir = project_dir.resolve()
    project_name = _sanitize_name(project_dir.name)
    digest = hashlib.sha1(str(project_dir).encode("utf-8")).hexdigest()[:10]
    return f"com.codex-loop.{project_name}-{digest}"


def service_paths(project_dir: Path, *, home_dir: Path | None = None) -> dict[str, Path]:
    project_dir = project_dir.resolve()
    loop_dir = project_dir / ".codex-loop"
    launch_agents_dir = (home_dir or Path.home()).resolve() / "Library" / "LaunchAgents"
    label = service_label(project_dir)
    return {
        "loop_dir": loop_dir,
        "metadata": loop_dir / "service.json",
        "heartbeat": loop_dir / "service-heartbeat.json",
        "log": loop_dir / "service.log",
        "plist": launch_agents_dir / f"{label}.plist",
    }


def _service_environment(heartbeat_path: Path) -> dict[str, str]:
    env = {"CODEX_LOOP_HEARTBEAT_PATH": str(heartbeat_path.resolve())}
    for key in ("PATH", "HOME", "SHELL", "CODEX_HOME"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _service_command(
    project_dir: Path,
    *,
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
        "--cycle-sleep-seconds",
        str(cycle_sleep_seconds),
    ]
    if retry_blocked:
        command.append("--retry-blocked")
    if max_cycles is not None:
        command.extend(["--max-cycles", str(max_cycles)])
    return command


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _launchctl_missing(result: subprocess.CompletedProcess[str] | Any) -> bool:
    stderr = (getattr(result, "stderr", "") or "").lower()
    stdout = (getattr(result, "stdout", "") or "").lower()
    return "no such process" in stderr or "could not find service" in stderr or "no such file" in stderr or "could not find service" in stdout


def _write_plist(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload))


def _bootstrap_service(
    *,
    run_cmd: Callable[..., Any],
    launchctl_cmd: str,
    domain: str,
    plist_path: Path,
) -> None:
    result = run_cmd(
        [launchctl_cmd, "bootstrap", domain, str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown launchctl error"
        raise RuntimeError(f"launchctl bootstrap failed: {detail}")


def _bootout_service(
    *,
    run_cmd: Callable[..., Any],
    launchctl_cmd: str,
    domain: str,
    plist_path: Path,
    ignore_missing: bool,
) -> None:
    result = run_cmd(
        [launchctl_cmd, "bootout", domain, str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    if ignore_missing and _launchctl_missing(result):
        return
    detail = result.stderr.strip() or result.stdout.strip() or "unknown launchctl error"
    raise RuntimeError(f"launchctl bootout failed: {detail}")


def install_service(
    project_dir: Path,
    *,
    retry_blocked: bool,
    cycle_sleep_seconds: float,
    max_cycles: int | None,
    launchctl_cmd: str = "launchctl",
    uid: int | None = None,
    home_dir: Path | None = None,
    platform: str = sys.platform,
    run_cmd: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    _require_darwin(platform)
    project_dir = project_dir.resolve()
    paths = service_paths(project_dir, home_dir=home_dir)
    label = service_label(project_dir)
    domain = _domain_for_uid(uid)
    reinstalled = paths["metadata"].exists() or paths["plist"].exists()
    if reinstalled:
        _bootout_service(
            run_cmd=run_cmd,
            launchctl_cmd=launchctl_cmd,
            domain=domain,
            plist_path=paths["plist"],
            ignore_missing=True,
        )
        paths["metadata"].unlink(missing_ok=True)
        paths["plist"].unlink(missing_ok=True)

    command = _service_command(
        project_dir,
        retry_blocked=retry_blocked,
        cycle_sleep_seconds=cycle_sleep_seconds,
        max_cycles=max_cycles,
    )
    plist_payload = {
        "Label": label,
        "ProgramArguments": command,
        "WorkingDirectory": str(project_dir),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(paths["log"]),
        "StandardErrorPath": str(paths["log"]),
        "EnvironmentVariables": _service_environment(paths["heartbeat"]),
    }
    paths["loop_dir"].mkdir(parents=True, exist_ok=True)
    _write_plist(paths["plist"], plist_payload)
    _bootstrap_service(
        run_cmd=run_cmd,
        launchctl_cmd=launchctl_cmd,
        domain=domain,
        plist_path=paths["plist"],
    )

    metadata = {
        "label": label,
        "domain": domain,
        "installed_at": _now(),
        "project_dir": str(project_dir),
        "plist_path": str(paths["plist"]),
        "log_path": str(paths["log"]),
        "heartbeat_path": str(paths["heartbeat"]),
        "command": command,
        "retry_blocked": retry_blocked,
        "cycle_sleep_seconds": cycle_sleep_seconds,
        "max_cycles": max_cycles,
        "heartbeat_stale_seconds": DEFAULT_HEARTBEAT_STALE_SECONDS,
        "reinstalled": reinstalled,
    }
    _write_json(paths["metadata"], metadata)
    return metadata


def service_status(
    project_dir: Path,
    *,
    launchctl_cmd: str = "launchctl",
    uid: int | None = None,
    home_dir: Path | None = None,
    platform: str = sys.platform,
    run_cmd: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    _require_darwin(platform)
    project_dir = project_dir.resolve()
    paths = service_paths(project_dir, home_dir=home_dir)
    metadata = _read_json(paths["metadata"])
    label = metadata.get("label") or service_label(project_dir)
    domain = metadata.get("domain") or _domain_for_uid(uid)
    plist_path = Path(metadata.get("plist_path", paths["plist"]))
    heartbeat_path = Path(metadata.get("heartbeat_path", paths["heartbeat"]))
    log_path = Path(metadata.get("log_path", paths["log"]))
    installed = paths["metadata"].exists() or plist_path.exists()

    if installed:
        result = run_cmd(
            [launchctl_cmd, "print", f"{domain}/{label}"],
            capture_output=True,
            text=True,
            check=False,
        )
        loaded = result.returncode == 0
        detail = result.stdout.strip() or result.stderr.strip()
    else:
        loaded = False
        detail = ""

    heartbeat = _read_json(heartbeat_path)
    heartbeat_stale_seconds = metadata.get(
        "heartbeat_stale_seconds", DEFAULT_HEARTBEAT_STALE_SECONDS
    )
    heartbeat_ts = _parse_timestamp(heartbeat.get("updated_at"))
    stale_heartbeat = False
    if isinstance(heartbeat_stale_seconds, (int, float)) and heartbeat_ts is not None:
        age_seconds = (datetime.now(UTC) - heartbeat_ts).total_seconds()
        stale_heartbeat = age_seconds > float(heartbeat_stale_seconds)

    return {
        "installed": installed,
        "loaded": loaded,
        "label": label,
        "domain": domain,
        "project_dir": str(project_dir),
        "plist_path": str(plist_path),
        "log_path": str(log_path),
        "heartbeat_path": str(heartbeat_path),
        "command": metadata.get("command", []),
        "retry_blocked": metadata.get("retry_blocked", False),
        "cycle_sleep_seconds": metadata.get("cycle_sleep_seconds"),
        "max_cycles": metadata.get("max_cycles"),
        "heartbeat_stale_seconds": heartbeat_stale_seconds,
        "stale_heartbeat": stale_heartbeat,
        "phase": heartbeat.get("phase"),
        "cycle": heartbeat.get("cycle"),
        "updated_at": heartbeat.get("updated_at"),
        "outcome": heartbeat.get("outcome"),
        "error_count": heartbeat.get("error_count"),
        "last_error": heartbeat.get("last_error"),
        "launchctl_detail": detail,
    }


def uninstall_service(
    project_dir: Path,
    *,
    launchctl_cmd: str = "launchctl",
    uid: int | None = None,
    home_dir: Path | None = None,
    platform: str = sys.platform,
    run_cmd: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    _require_darwin(platform)
    project_dir = project_dir.resolve()
    paths = service_paths(project_dir, home_dir=home_dir)
    metadata = _read_json(paths["metadata"])
    label = metadata.get("label") or service_label(project_dir)
    domain = metadata.get("domain") or _domain_for_uid(uid)
    plist_path = Path(metadata.get("plist_path", paths["plist"]))
    if not paths["metadata"].exists() and not plist_path.exists():
        raise RuntimeError(f"No service metadata found for {project_dir}")

    if plist_path.exists():
        _bootout_service(
            run_cmd=run_cmd,
            launchctl_cmd=launchctl_cmd,
            domain=domain,
            plist_path=plist_path,
            ignore_missing=True,
        )
        plist_path.unlink(missing_ok=True)
    paths["metadata"].unlink(missing_ok=True)
    return {
        "label": label,
        "domain": domain,
        "plist_path": str(plist_path),
        "heartbeat_path": metadata.get("heartbeat_path", str(paths["heartbeat"])),
        "log_path": metadata.get("log_path", str(paths["log"])),
    }
