from __future__ import annotations

from pathlib import Path
import subprocess


class Verifier:
    def run(self, commands: list[str], cwd: Path) -> tuple[bool, list[dict[str, object]]]:
        results: list[dict[str, object]] = []
        all_passed = True
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
            if completed.returncode != 0:
                all_passed = False
        return all_passed, results

