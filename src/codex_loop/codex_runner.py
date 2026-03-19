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
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"Expected JSON object from {path}"
        raise ValueError(msg)
    return loaded


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
    ) -> list[str]:
        base = ["codex", "exec"]
        if session_id:
            base.append("resume")
        base.extend(
            [
                "-c",
                'approval_policy="never"',
                "-c",
                'sandbox_mode="workspace-write"',
                "--json",
                "--model",
                model,
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
            ]
        )
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
            self._invoke(command, init_prompt, self.project_dir)
            result = _read_json_file(output_path)
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
        command = self.build_run_command(
            task=task,
            prompt=prompt,
            schema_path=schema_path,
            output_path=output_path,
            session_id=resume_session,
            model=config.codex.model,
        )
        stdout = self._invoke(command, prompt, working_directory)
        result = _read_json_file(output_path)
        if "session_id" not in result:
            session_id = _extract_session_id(stdout)
            if session_id:
                result["session_id"] = session_id
        return result

    @staticmethod
    def _invoke(command: list[str], prompt: str, cwd: Path) -> str:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=prompt,
            capture_output=True,
            text=True,
        )
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
            "Return only the structured result matching the provided schema."
        )
