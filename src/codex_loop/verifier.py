from __future__ import annotations

from pathlib import Path
import subprocess


class Verifier:
    def run(
        self,
        commands: list[str],
        cwd: Path,
        pass_requires_all: bool = True,
        timeout_seconds: int = 300,
    ) -> tuple[bool, list[dict[str, object]]]:
        if not commands:
            return True, []
        results: list[dict[str, object]] = []
        passed_count = 0
        for command in commands:
            try:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                results.append(
                    {
                        "command": command,
                        "exit_code": completed.returncode,
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                        "timed_out": False,
                    }
                )
                if completed.returncode == 0:
                    passed_count += 1
            except subprocess.TimeoutExpired as exc:
                results.append(
                    {
                        "command": command,
                        "exit_code": None,
                        "stdout": exc.stdout or "",
                        "stderr": exc.stderr or "",
                        "timed_out": True,
                    }
                )
        if pass_requires_all:
            return passed_count == len(commands), results
        return passed_count > 0, results
