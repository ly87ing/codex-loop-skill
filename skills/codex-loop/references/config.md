# Config Reference

`codex-loop.yaml` is the runtime contract for the supervisor.

## Core Sections

`project`
- `name`: human-readable project name

`goal`
- `summary`: one-line goal statement
- `done_when`: explicit completion criteria used in prompts and reporting

`execution`
- `sandbox`: intended sandbox mode for Codex
- `approval`: intended approval policy
- `max_iterations`: hard upper bound for loop iterations
- `max_no_progress_iterations`: fail-safe for repeated non-progress
- `worktree.enabled`: whether to run inside a temporary worktree
- `worktree.branch_prefix`: branch prefix for generated worktree branches

`codex`
- `model`: model name passed to `codex exec`
- `use_json`: whether structured output is required
- `output_schema`: schema path used for per-iteration results

`verification`
- `commands`: commands run after every agent iteration
- `pass_requires_all`: all commands must pass in the first version

`tasks`
- `strategy`: `sequential` in the first version
- `source_dir`: task document directory

`logging`
- `save_prompts`: whether prompts should be persisted
- `save_jsonl`: whether raw Codex JSONL should be persisted

## Format Note

The generated file is JSON-compatible YAML. That keeps the first version dependency-light while staying valid YAML.

