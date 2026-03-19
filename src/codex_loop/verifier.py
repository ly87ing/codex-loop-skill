from __future__ import annotations

from pathlib import Path
import subprocess


class Verifier:
    def run(
        self,
        commands: list[str],
        cwd: Path,
        pass_requires_all: bool = True,
    ) -> tuple[bool, list[dict[str, object]]]:
        if not commands:
            return False, [
                {
                    "command": "",
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "No verification commands configured.",
                }
            ]
        results: list[dict[str, object]] = []
        passed_count = 0
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
            )
            results.append(
                {
                    "command": command,
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
            if completed.returncode == 0:
                passed_count += 1
        if pass_requires_all:
            return passed_count == len(commands), results
        return passed_count > 0, results
