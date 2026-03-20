from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path


def _now() -> datetime:
    return datetime.now(UTC)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(slots=True)
class RunLock:
    path: Path
    stale_seconds: int

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = {}
            pid = int(existing.get("pid", -1))
            started_at_raw = str(existing.get("started_at", ""))
            is_stale = self._is_stale(started_at_raw)
            if _pid_alive(pid) and not is_stale:
                msg = (
                    f"Another codex-loop run is already active (pid={pid}).\n"
                    f"Wait for it to finish, or stop it: kill {pid}\n"
                    "If the process is already gone and this error persists, delete the lock file:\n"
                    f"  rm {self.path}"
                )
                raise RuntimeError(msg)
        payload = {
            "pid": os.getpid(),
            "started_at": _now().isoformat(),
        }
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def release(self) -> None:
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.path.unlink(missing_ok=True)
                return
            if int(payload.get("pid", -1)) == os.getpid():
                self.path.unlink(missing_ok=True)

    def _is_stale(self, started_at_raw: str) -> bool:
        try:
            started_at = datetime.fromisoformat(started_at_raw)
        except ValueError:
            return True
        age = (_now() - started_at).total_seconds()
        return age > self.stale_seconds
