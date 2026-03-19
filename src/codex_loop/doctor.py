from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from .config import CodexLoopConfig, OperatorConfig, _load_yaml_or_json
from .init_flow import AGENT_RESULT_SCHEMA
from .state_store import StateStore
from .task_graph import TaskGraph


@dataclass(slots=True)
class DoctorReport:
    checked: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _merge_missing_defaults(target: dict[str, Any], defaults: dict[str, Any]) -> bool:
    changed = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
            changed = True
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            if _merge_missing_defaults(target[key], value):
                changed = True
    return changed


def _append_operator_cleanup_warnings(report: DoctorReport, config: CodexLoopConfig) -> None:
    cleanup = config.operator.cleanup
    if cleanup.keep == 0 and cleanup.older_than_days is None:
        report.warnings.append(
            "operator.cleanup.keep=0 with no older_than_days will delete all matching artifacts on apply. Suggested remediation: set operator.cleanup.keep to at least 1 or add operator.cleanup.older_than_days."
        )
    for directory_name, keep_value in cleanup.directory_keep.items():
        directory_age = cleanup.directory_older_than_days.get(
            directory_name,
            cleanup.older_than_days,
        )
        if keep_value == 0 and directory_age is None:
            report.warnings.append(
                f"operator.cleanup.directory_keep.{directory_name}=0 with no age threshold will delete all {directory_name} artifacts on apply. Suggested remediation: set operator.cleanup.directory_keep.{directory_name} to at least 1 or add operator.cleanup.directory_older_than_days.{directory_name}."
            )


def _append_watchdog_warnings(report: DoctorReport, project_dir: Path) -> None:
    for name in ("daemon-watchdog.json", "service-watchdog.json"):
        path = project_dir / ".codex-loop" / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("phase") == "exhausted":
            report.warnings.append(
                f"{path.relative_to(project_dir)} watchdog is exhausted and requires operator intervention before unattended execution can continue safely."
            )


def run_doctor(project_dir: Path, *, repair: bool) -> DoctorReport:
    report = DoctorReport()
    config_path = project_dir / "codex-loop.yaml"
    if not config_path.exists():
        report.errors.append("Missing config file: codex-loop.yaml")
        return report
    raw_data = _load_yaml_or_json(config_path.read_text(encoding="utf-8"))
    report.checked.append("codex-loop.yaml")
    operator_defaults = asdict(OperatorConfig())
    working_data = json.loads(json.dumps(raw_data))
    operator_data = working_data.get("operator")
    operator_changed = False
    if operator_data is None:
        working_data["operator"] = operator_defaults
        operator_changed = True
    elif isinstance(operator_data, dict):
        operator_changed = _merge_missing_defaults(operator_data, operator_defaults)
    if operator_changed:
        if repair:
            config_path.write_text(
                json.dumps(working_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            raw_data = working_data
            report.fixed.append("codex-loop.yaml operator defaults")
        else:
            report.warnings.append("codex-loop.yaml is missing operator defaults")
    try:
        config = CodexLoopConfig.from_dict(raw_data, project_dir)
    except (ValueError, TypeError, AttributeError) as exc:
        report.errors.append(str(exc))
        return report
    _append_operator_cleanup_warnings(report, config)
    _append_watchdog_warnings(report, project_dir)

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
