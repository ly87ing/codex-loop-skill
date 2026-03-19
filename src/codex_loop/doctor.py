from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from .config import CodexLoopConfig
from .init_flow import AGENT_RESULT_SCHEMA
from .state_store import StateStore
from .task_graph import TaskGraph


@dataclass(slots=True)
class DoctorReport:
    checked: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run_doctor(project_dir: Path, *, repair: bool) -> DoctorReport:
    config = CodexLoopConfig.from_file(project_dir / "codex-loop.yaml")
    report = DoctorReport()
    report.checked.append("codex-loop.yaml")

    tasks_dir = project_dir / config.tasks.source_dir
    task_graph = TaskGraph(tasks_dir)
    tasks = task_graph.discover()
    task_ids = [task.task_id for task in tasks]
    if not task_ids:
        report.errors.append(f"No task files found in {tasks_dir}")
        return report
    report.checked.append(str(tasks_dir.relative_to(project_dir)))

    schema_path = project_dir / config.codex.output_schema
    if schema_path.exists():
        report.checked.append(str(schema_path.relative_to(project_dir)))
    elif repair:
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(json.dumps(AGENT_RESULT_SCHEMA, indent=2), encoding="utf-8")
        report.fixed.append(str(schema_path.relative_to(project_dir)))
    else:
        report.errors.append(f"Missing schema: {schema_path.relative_to(project_dir)}")

    state_path = project_dir / ".codex-loop" / "state.json"
    store = StateStore(state_path)
    if not state_path.exists():
        if repair:
            store.create_initial(
                project_name=config.project.name,
                source_prompt="",
                tasks=task_ids,
            )
            report.fixed.append(".codex-loop/state.json")
        else:
            report.errors.append("Missing state file: .codex-loop/state.json")
            return report

    if repair:
        store.reconcile_tasks(task_ids)
        report.fixed.append("tasks reconciled")
    else:
        state = store.load()
        state_task_ids = list(state.get("tasks", {}).keys())
        if state_task_ids != task_ids:
            report.warnings.append("tasks state does not match task files")
        else:
            report.checked.append(".codex-loop/state.json")

    return report


def render_doctor_report(report: DoctorReport) -> str:
    lines: list[str] = []
    if report.checked:
        lines.append("Checked:")
        lines.extend(f"- {item}" for item in report.checked)
    if report.fixed:
        lines.append("Fixed:")
        lines.extend(f"- {item}" for item in report.fixed)
    if report.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in report.warnings)
    if report.errors:
        lines.append("Errors:")
        lines.extend(f"- {item}" for item in report.errors)
    return "\n".join(lines)
