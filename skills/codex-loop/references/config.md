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
- `max_consecutive_task_failures`: task-level circuit breaker; when a single task fails this many times consecutively the task is marked blocked and skipped, the next pending task is promoted, and the loop continues; `0` disables it; default `5`
- `iteration_timeout_seconds`: timeout for each `codex exec` or `codex exec resume` call
- `iteration_backoff_seconds`: base sleep between non-terminal iterations
- `iteration_backoff_jitter_seconds`: random jitter added on top of the base backoff
- `resume_fallback_to_fresh`: retry once without `resume` when the saved session is stale or invalid (e.g. "session not found"); transient failures such as timeouts and network errors are not treated as stale sessions and do not trigger this fallback
- `worktree.enabled`: whether to run inside a temporary worktree
- `worktree.branch_prefix`: branch prefix for generated worktree branches

`codex`
- `model`: model name passed to `codex exec`
- `use_json`: whether structured output is required
- `output_schema`: schema path used for per-iteration results

`verification`
- `commands`: commands run after every agent iteration
- `pass_requires_all`: all commands must pass in the first version
- `timeout_seconds`: per-command timeout in seconds; timed-out commands count as failures; default `300`

`tasks`
- `strategy`: `sequential` in the first version
- `source_dir`: task document directory

`logging`
- `save_prompts`: whether prompts should be persisted
- `save_jsonl`: whether raw Codex JSONL should be persisted

`operator`
- `events.default_limit`: default `events` limit when the CLI flag is omitted
- `cleanup.keep`: default artifact keep count
- `cleanup.older_than_days`: default artifact/worktree age threshold
- `cleanup.directory_keep`: per-directory keep overrides for `logs`, `runs`, and `prompts`
- `cleanup.directory_older_than_days`: per-directory age overrides for `logs`, `runs`, and `prompts`

`hooks`
- `post_init`: local commands run after `codex-loop init`
- `pre_iteration`: local commands run before each task iteration
- `post_iteration`: local commands run after each task iteration
- `on_completed`: local commands run after the loop reaches `completed`
- `on_blocked`: local commands run after the loop reaches `blocked`
- `failure_policy`: `ignore` or `block` for `post_init`, `pre_iteration`, and `post_iteration`
- `timeout_seconds`: timeout for each hook command

## Blocker Taxonomy

When the loop blocks, state and metrics persist a `blocker_code` alongside the human-readable reason. Current codes include:

- `hook_failure`
- `agent_blocked`
- `runner_failure_circuit_breaker`
- `verification_failure_circuit_breaker`
- `task_failure_circuit_breaker`: single task exceeded `max_consecutive_task_failures`; task is skipped, loop continues
- `no_progress_limit`
- `max_iterations`
- `no_selectable_task`

## Format Note

The generated file is JSON-compatible YAML. That keeps the first version dependency-light while staying valid YAML.
