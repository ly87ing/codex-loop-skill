from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_loop.reporting import (
    format_events_summary,
    format_events_timeline,
    load_events_timeline,
    summarize_events,
)
from codex_loop.state_store import StateStore


class ReportingTests(unittest.TestCase):
    def test_events_timeline_includes_hook_and_blocked_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            hooks_dir = root / ".codex-loop" / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            (hooks_dir / "post_iteration.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-19T00:00:00+00:00",
                        "command": "echo hi",
                        "success": True,
                        "exit_code": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rendered = format_events_timeline(root, limit=10)

            self.assertIn("runner_failure", rendered)
            self.assertIn("hook:post_iteration", rendered)
            self.assertIn("blocked:no_progress_limit", rendered)

    def test_events_timeline_can_filter_and_export_structured_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.record_iteration(
                task_id="002-polish",
                summary="Updated polish layer",
                fingerprint="002|continue",
                files_changed=["src/polish.py"],
                verification_passed=False,
                agent_status="continue",
            )
            hooks_dir = root / ".codex-loop" / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            (hooks_dir / "post_iteration.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-19T00:00:00+00:00",
                        "command": "echo hi",
                        "success": True,
                        "exit_code": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            events = load_events_timeline(
                root,
                limit=10,
                task_id="002-polish",
                event_type="iteration:continue",
            )
            rendered = format_events_timeline(
                root,
                limit=10,
                task_id="002-polish",
                event_type="iteration:continue",
            )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["task_id"], "002-polish")
            self.assertEqual(events[0]["label"], "iteration:continue")
            self.assertIn("iteration:continue", rendered)
            self.assertNotIn("runner_failure", rendered)

    def test_events_timeline_can_filter_by_time_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.record_iteration(
                task_id="002-polish",
                summary="Updated polish layer",
                fingerprint="002|continue",
                files_changed=["src/polish.py"],
                verification_passed=False,
                agent_status="continue",
            )
            state = store.load()
            state["history"][0]["timestamp"] = "2026-03-18T00:00:00+00:00"
            state["history"][1]["timestamp"] = "2026-03-20T00:00:00+00:00"
            store.save(state)

            events = load_events_timeline(
                root,
                limit=10,
                since="2026-03-19T00:00:00+00:00",
                until="2026-03-21T00:00:00+00:00",
            )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["task_id"], "002-polish")

    def test_events_summary_aggregates_by_label_and_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.record_runner_failure(
                task_id="001-foundation",
                reason="runner failed once",
            )
            store.record_iteration(
                task_id="002-polish",
                summary="Updated polish layer",
                fingerprint="002|continue",
                files_changed=["src/polish.py"],
                verification_passed=False,
                agent_status="continue",
            )

            events = load_events_timeline(root, limit=10)
            summary = summarize_events(events)
            rendered = format_events_summary(events)

            self.assertEqual(summary["total_events"], 2)
            self.assertEqual(summary["by_label"]["runner_failure"], 1)
            self.assertEqual(summary["by_label"]["iteration:continue"], 1)
            self.assertEqual(summary["by_task"]["001-foundation"], 1)
            self.assertEqual(summary["by_task"]["002-polish"], 1)
            self.assertIn("total_events: 2", rendered)
            self.assertIn("iteration:continue: 1", rendered)

    def test_events_summary_tracks_blocker_codes_and_blocked_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )

            events = load_events_timeline(root, limit=10)
            summary = summarize_events(events)
            rendered = format_events_summary(events)

            self.assertEqual(summary["by_blocker_code"]["no_progress_limit"], 1)
            self.assertEqual(summary["blocked_tasks"], ["001-foundation"])
            self.assertIn("by_blocker_code:", rendered)
            self.assertIn("no_progress_limit: 1", rendered)

    def test_events_summary_tracks_latest_blocked_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root / ".codex-loop" / "state.json")
            store.create_initial("demo", "Build demo", ["001-foundation", "002-polish"])
            store.mark_blocked(
                "001-foundation",
                reason="Reached no-progress limit.",
                code="no_progress_limit",
            )
            store.mark_blocked(
                "002-polish",
                reason="Runner circuit breaker tripped.",
                code="runner_failure_circuit_breaker",
            )
            state = store.load()
            state["history"][-2]["timestamp"] = "2026-03-19T00:00:00+00:00"
            state["history"][-1]["timestamp"] = "2026-03-20T00:00:00+00:00"
            store.save(state)

            summary = summarize_events(load_events_timeline(root, limit=10))
            rendered = format_events_summary(load_events_timeline(root, limit=10))

            self.assertEqual(
                summary["latest_blocked"]["task_id"],
                "002-polish",
            )
            self.assertEqual(
                summary["latest_blocked"]["blocker_code"],
                "runner_failure_circuit_breaker",
            )
            self.assertIn("latest_blocked:", rendered)
            self.assertIn("runner_failure_circuit_breaker", rendered)


if __name__ == "__main__":
    unittest.main()
