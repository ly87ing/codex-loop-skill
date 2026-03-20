from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .config import CodexLoopConfig
from .init_flow import InitResult, TaskDraft
from .task_graph import Task


INIT_RESULT_SCHEMA = {
    "type": "object",
    "required": [
        "project_name",
        "goal_summary",
        "done_when",
        "spec_markdown",
        "plan_markdown",
        "tasks",
        "verification_commands",
    ],
    "properties": {
        "project_name": {"type": "string"},
        "goal_summary": {"type": "string"},
        "done_when": {"type": "array", "items": {"type": "string"}},
        "spec_markdown": {"type": "string"},
        "plan_markdown": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["slug", "title", "markdown"],
                "properties": {
                    "slug": {"type": "string"},
                    "title": {"type": "string"},
                    "markdown": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "verification_commands": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "additionalProperties": False,
}


def _extract_session_id(jsonl: str) -> str | None:
    for raw_line in jsonl.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        msg = f"Expected output file was not created: {path}"
        raise FileNotFoundError(msg)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"Expected JSON object from {path}"
        raise ValueError(msg)
    return loaded


def _resume_error_reason(message: str) -> str:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith(("Command:", "STDOUT:", "STDERR:")):
            continue
        return line
    return "resume failed"


@dataclass(slots=True)
class CodexRunner:
    project_dir: Path

    def build_run_command(
        self,
        *,
        task: Task,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        session_id: str | None,
        model: str,
        sandbox: str,
        approval: str,
    ) -> list[str]:
        base = ["codex", "exec"]
        if session_id:
            base.append("resume")
        base.extend(
            [
                "-c",
                f'approval_policy="{approval}"',
                "-c",
                f'sandbox_mode="{sandbox}"',
                "--json",
                "--model",
                model,
            ]
        )
        # `codex exec resume` does not support -s/--sandbox; use -c only.
        # For fresh exec, also pass -s as the authoritative CLI flag so the
        # sandbox policy is enforced even if the -c key name ever drifts.
        if not session_id:
            base.extend(["-s", sandbox])
        # `codex exec resume` does not accept --output-schema; only fresh exec does.
        if not session_id:
            base.extend(["--output-schema", str(schema_path)])
        base.extend(["--output-last-message", str(output_path)])
        if session_id:
            base.extend([session_id, "-"])
        else:
            base.append("-")
        return base

    def initialize_from_prompt(
        self,
        *,
        prompt: str,
        model: str,
    ) -> InitResult:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            schema_path = tmp / "init.schema.json"
            output_path = tmp / "init-result.json"
            schema_path.write_text(json.dumps(INIT_RESULT_SCHEMA, indent=2), encoding="utf-8")
            command = [
                "codex",
                "exec",
                "--skip-git-repo-check",
                "-c",
                'approval_policy="never"',
                "-c",
                'sandbox_mode="workspace-write"',
                "-s",
                "workspace-write",
                "--json",
                "--model",
                model,
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ]
            init_prompt = self._build_init_prompt(prompt)
            self._invoke(
                command,
                init_prompt,
                self.project_dir,
                timeout_seconds=1800,
            )
            result = _read_json_file(output_path)
        self._validate_init_result(result)
        return InitResult(
            project_name=str(result["project_name"]),
            goal_summary=str(result["goal_summary"]),
            done_when=[str(item) for item in result["done_when"]],
            spec_markdown=str(result["spec_markdown"]),
            plan_markdown=str(result["plan_markdown"]),
            tasks=[
                TaskDraft(
                    slug=str(task["slug"]),
                    title=str(task["title"]),
                    markdown=str(task["markdown"]),
                )
                for task in result["tasks"]
            ],
            verification_commands=[str(item) for item in result["verification_commands"]],
        )

    def run_task(
        self,
        *,
        config: CodexLoopConfig,
        task: Task,
        state: dict[str, Any],
        working_directory: Path,
        resume_session: str | None,
    ) -> dict[str, Any]:
        output_dir = config.project_dir / ".codex-loop" / "runs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task.task_id}-last.json"
        schema_path = config.project_dir / config.codex.output_schema
        prompt = self._build_run_prompt(config, task, state)
        self._write_prompt_artifact(config, task.task_id, prompt)
        if output_path.exists():
            output_path.unlink()
        command = self.build_run_command(
            task=task,
            prompt=prompt,
            schema_path=schema_path,
            output_path=output_path,
            session_id=resume_session,
            model=config.codex.model,
            sandbox=config.execution.sandbox,
            approval=config.execution.approval,
        )
        resume_fallback_used = False
        resume_failure_reason: str | None = None
        try:
            stdout = self._invoke(
                command,
                prompt,
                working_directory,
                timeout_seconds=config.execution.iteration_timeout_seconds,
            )
        except RuntimeError as exc:
            if (
                resume_session
                and config.execution.resume_fallback_to_fresh
                and not self._is_transient_error(str(exc))
                and self._should_retry_without_resume(str(exc))
            ):
                resume_fallback_used = True
                resume_failure_reason = _resume_error_reason(str(exc))
                if output_path.exists():
                    output_path.unlink()
                fallback_command = self.build_run_command(
                    task=task,
                    prompt=prompt,
                    schema_path=schema_path,
                    output_path=output_path,
                    session_id=None,
                    model=config.codex.model,
                    sandbox=config.execution.sandbox,
                    approval=config.execution.approval,
                )
                stdout = self._invoke(
                    fallback_command,
                    prompt,
                    working_directory,
                    timeout_seconds=config.execution.iteration_timeout_seconds,
                )
            else:
                raise
        self._write_stdout_artifact(config, task.task_id, stdout)
        result = _read_json_file(output_path)
        self._validate_run_result(result, task.task_id)
        result["resume_attempted"] = bool(resume_session)
        result["resume_fallback_used"] = resume_fallback_used
        result["resume_failure_reason"] = resume_failure_reason
        if "session_id" not in result:
            session_id = _extract_session_id(stdout)
            if session_id:
                result["session_id"] = session_id
        return result

    @staticmethod
    def _invoke(
        command: list[str],
        prompt: str,
        cwd: Path,
        *,
        timeout_seconds: int,
    ) -> str:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            def _decode(raw: bytes | str | None) -> str:
                if raw is None:
                    return ""
                return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            msg = (
                "Codex command timed out.\n"
                f"Command: {' '.join(command)}\n"
                f"Timeout: {timeout_seconds}s\n"
                f"STDOUT:\n{_decode(exc.stdout)}\n"
                f"STDERR:\n{_decode(exc.stderr)}"
            )
            raise RuntimeError(msg) from exc
        except FileNotFoundError as exc:
            msg = (
                f"Codex executable not found: {command[0]}\n"
                "Ensure `codex` is installed and on PATH."
            )
            raise RuntimeError(msg) from exc
        except OSError as exc:
            msg = (
                f"OS error running codex command: {exc}\n"
                f"Command: {' '.join(command)}"
            )
            raise RuntimeError(msg) from exc
        if completed.returncode != 0:
            msg = (
                "Codex command failed.\n"
                f"Command: {' '.join(command)}\n"
                f"STDOUT:\n{completed.stdout}\n"
                f"STDERR:\n{completed.stderr}"
            )
            raise RuntimeError(msg)
        return completed.stdout

    @staticmethod
    def _is_transient_error(message: str) -> bool:
        """Return True for temporary infrastructure failures (network, timeout, kill).
        Transient errors must not trigger resume fallback — the session may still be valid.
        """
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "timed out",
                "timeout",
                "connection reset",
                "connection refused",
                "broken pipe",
                "network",
                "killed",
                "sigkill",
                "sigterm",
                "rate limit",
                "429",
                "500",
                "502",
                "503",
                "overloaded",
                "temporarily unavailable",
            )
        )

    @staticmethod
    def _should_retry_without_resume(message: str) -> bool:
        """Return True when the error indicates the saved session is no longer valid
        and a fresh exec (without resume) is the correct recovery.

        Only match tokens that specifically indicate session invalidity in the
        STDERR/body of the error — not tokens that appear in the command line
        (e.g. "resume" appears in "codex exec resume <id>" even for unrelated
        failures such as process crashes or permission errors).
        """
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "session not found",
                "invalid session",
                "conversation not found",
                "session expired",
                "session has expired",
                "unknown session",
                "no such session",
            )
        )

    @staticmethod
    def _build_init_prompt(user_prompt: str) -> str:
        return (
            "You are preparing a file-driven autonomous Codex loop project.\n"
            "Turn the user's request into a concise spec, a concrete implementation plan, "
            "a sequential task list, and verification commands.\n"
            "Keep the scope realistic for a first working iteration.\n\n"
            f"User request:\n{user_prompt}\n"
        )

    @staticmethod
    def _build_run_prompt(
        config: CodexLoopConfig,
        task: Task,
        state: dict[str, Any],
    ) -> str:
        history = state.get("history", [])[-3:]
        history_block = "\n".join(
            f"- Iteration {item['iteration']}: {item['summary']}"
            for item in history
        )
        if not history_block:
            history_block = "- No prior iterations."

        # Inject the last verification failure output so Codex can see exactly
        # what broke, rather than having to guess from a text summary.
        verification_block = ""
        task_state = state.get("tasks", {}).get(task.task_id, {})
        last_verification = task_state.get("last_verification_results")
        if last_verification and isinstance(last_verification, list):
            failed = [r for r in last_verification if r.get("exit_code") != 0 or r.get("timed_out")]
            if failed:
                parts = ["## Last Verification Output (FAILED — fix these before reporting complete)"]
                for r in failed:
                    cmd = r.get("command", "")
                    exit_code = r.get("exit_code")
                    timed_out = r.get("timed_out", False)
                    stdout = str(r.get("stdout", ""))[:1500].strip()
                    stderr = str(r.get("stderr", ""))[:1500].strip()
                    parts.append(f"Command: {cmd}")
                    if timed_out:
                        parts.append("Result: TIMED OUT")
                    else:
                        parts.append(f"Exit code: {exit_code}")
                    if stdout:
                        parts.append(f"stdout:\n{stdout}")
                    if stderr:
                        parts.append(f"stderr:\n{stderr}")
                verification_block = "\n".join(parts) + "\n\n"

        return (
            "You are executing one task in a file-driven autonomous Codex loop.\n"
            "Work only on the current task. Make concrete file changes in the repo, "
            "then report structured progress.\n\n"
            f"Project goal: {config.goal.summary}\n"
            f"Done when:\n- " + "\n- ".join(config.goal.done_when) + "\n\n"
            f"Current task id: {task.task_id}\n"
            f"Current task title: {task.title}\n"
            f"Task document:\n{task.body}\n\n"
            f"Recent loop history:\n{history_block}\n\n"
            + verification_block
            + "Return only the structured result matching the provided schema."
        )

    def _write_prompt_artifact(
        self,
        config: CodexLoopConfig,
        task_id: str,
        prompt: str,
    ) -> None:
        if not config.logging.save_prompts:
            return
        try:
            prompts_dir = config.project_dir / ".codex-loop" / "prompts"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            iteration = len(self._safe_history(config.project_dir)) + 1
            (prompts_dir / f"{iteration:04d}-{task_id}.txt").write_text(
                prompt,
                encoding="utf-8",
            )
        except OSError:
            pass  # Prompt artifact is observability data; I/O failure must not crash the loop

    def _write_stdout_artifact(
        self,
        config: CodexLoopConfig,
        task_id: str,
        stdout: str,
    ) -> None:
        if not config.logging.save_jsonl:
            return
        try:
            logs_dir = config.project_dir / ".codex-loop" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            iteration = len(self._safe_history(config.project_dir)) + 1
            (logs_dir / f"{iteration:04d}-{task_id}.jsonl").write_text(
                stdout,
                encoding="utf-8",
            )
        except OSError:
            pass  # Stdout artifact is observability data; I/O failure must not crash the loop

    @staticmethod
    def _safe_history(project_dir: Path) -> list[dict[str, Any]]:
        state_path = project_dir / ".codex-loop" / "state.json"
        if not state_path.exists():
            return []
        try:
            state = _read_json_file(state_path)
        except Exception:
            return []
        history = state.get("history", [])
        return history if isinstance(history, list) else []

    @staticmethod
    def _validate_init_result(result: dict[str, Any]) -> None:
        required = [
            "project_name",
            "goal_summary",
            "done_when",
            "spec_markdown",
            "plan_markdown",
            "tasks",
            "verification_commands",
        ]
        missing = [field for field in required if field not in result]
        if missing:
            msg = f"Init result missing fields: {missing}"
            raise ValueError(msg)
        if not isinstance(result["tasks"], list) or not result["tasks"]:
            msg = "Init result must include at least one task."
            raise ValueError(msg)
        if not isinstance(result["verification_commands"], list) or not result["verification_commands"]:
            msg = "Init result must include at least one verification command."
            raise ValueError(msg)

    @staticmethod
    def _validate_run_result(result: dict[str, Any], expected_task_id: str) -> None:
        required = [
            "status",
            "summary",
            "task_id",
            "files_changed",
            "verification_expected",
            "needs_resume",
            "blockers",
            "next_action",
        ]
        missing = [field for field in required if field not in result]
        if missing:
            msg = f"Run result missing fields: {missing}"
            raise ValueError(msg)
        if result["task_id"] != expected_task_id:
            msg = (
                f"Run result task_id mismatch: expected {expected_task_id}, "
                f"got {result['task_id']}"
            )
            raise ValueError(msg)
