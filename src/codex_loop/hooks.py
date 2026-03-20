from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


class HookRunner:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir

    def run(
        self,
        *,
        event_name: str,
        commands: list[str],
        cwd: Path,
        env: dict[str, object] | None = None,
        timeout_seconds: int,
    ) -> list[dict[str, Any]]:
        if not commands:
            return []
        self.log_dir.mkdir(parents=True, exist_ok=True)
        merged_env = os.environ.copy()
        merged_env["CODEX_LOOP_EVENT"] = event_name
        for key, value in (env or {}).items():
            if value is None:
                continue
            merged_env[key] = str(value)

        results: list[dict[str, Any]] = []
        log_path = self.log_dir / f"{event_name}.jsonl"
        for index, command in enumerate(commands, start=1):
            result = self._run_one(
                command=command,
                cwd=cwd,
                env=merged_env,
                timeout_seconds=timeout_seconds,
                index=index,
            )
            results.append(result)
            try:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result) + "\n")
            except OSError:
                pass
        return results

    @staticmethod
    def first_failure(results: list[dict[str, Any]]) -> dict[str, Any] | None:
        for result in results:
            if not bool(result.get("success", False)):
                return result
        return None

    @staticmethod
    def failure_reason(
        event_name: str,
        result: dict[str, Any] | None,
    ) -> str | None:
        if result is None:
            return None
        command = str(result.get("command", ""))
        if result.get("timed_out"):
            return f"Hook failure during {event_name}: timed out running `{command}`."
        exit_code = result.get("exit_code")
        return (
            f"Hook failure during {event_name}: command `{command}` exited with {exit_code}."
        )

    @staticmethod
    def _run_one(
        *,
        command: str,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: int,
        index: int,
    ) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return {
                "timestamp": _now(),
                "index": index,
                "command": command,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "timed_out": False,
                "success": completed.returncode == 0,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "timestamp": _now(),
                "index": index,
                "command": command,
                "exit_code": None,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "timed_out": True,
                "success": False,
            }
