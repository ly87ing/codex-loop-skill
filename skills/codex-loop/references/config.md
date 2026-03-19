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
- `max_consecutive_runner_failures`: circuit breaker for repeated Codex command failures
- `max_consecutive_verification_failures`: optional circuit breaker for repeated red verification runs; `0` disables it
- `iteration_timeout_seconds`: timeout for each `codex exec` or `codex exec resume` call
- `iteration_backoff_seconds`: optional sleep between iterations
- `resume_fallback_to_fresh`: retry once without `resume` when the saved session is stale
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

`hooks`
- `post_init`: local commands run after `codex-loop init`
- `pre_iteration`: local commands run before each task iteration
- `post_iteration`: local commands run after each task iteration
- `timeout_seconds`: timeout for each hook command

## Format Note

The generated file is JSON-compatible YAML. That keeps the first version dependency-light while staying valid YAML.
