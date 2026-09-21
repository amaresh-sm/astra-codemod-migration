import json
import tempfile
import unittest
from pathlib import Path

from astra_harness.scheduler import (
    QueueJob,
    live_generation_containers,
    latest_activity_time,
    lifecycle_files,
    load_queue,
    run_id_for,
    state_template,
)


class SchedulerQueueTests(unittest.TestCase):
    def test_loads_requested_order_and_limit(self) -> None:
        queue = Path(__file__).resolve().parents[1] / "config/candidate-generation-queue.json"
        limit, jobs = load_queue(queue)
        self.assertEqual(limit, 4)
        self.assertEqual([job.model for job in jobs], [
            "gemini-3.7-flash",
            "glm-5.2",
            "gemini-3.7-flash",
            "qwen-3.8",
            "glm-5.2",
            "glm-5.2",
            "qwen-3.8",
            "qwen-3.8",
        ])
        self.assertEqual(
            [job.reasoning for job in jobs],
            ["high", "medium", "medium", "high", "medium", "medium", "high", "high"],
        )
        self.assertEqual([job.environment for job in jobs], ["prod"] * 8)

    def test_run_ids_are_ordered_and_distinct_for_repeated_jobs(self) -> None:
        first = QueueJob("glm-1", "glm-5.2", "medium", "prod", 2)
        second = QueueJob("glm-2", "glm-5.2", "medium", "prod", 5)
        self.assertEqual(run_id_for(first, "20260919"), "openhands-glm-5-2-medium-prod-20260919-q02")
        self.assertNotEqual(run_id_for(first, "20260919"), run_id_for(second, "20260919"))

    def test_live_container_filter_ignores_other_tasks_and_stale_metadata(self) -> None:
        output = "\n".join([
            "astra-generate-migrate-jscodeshift-runner-to-rust-openhands-a",
            "astra-generate-migrate-jscodeshift-runner-to-rust-openhands-b",
            "astra-generate-other-task-openhands-c",
            "stale-metadata-only",
        ])
        self.assertEqual(
            live_generation_containers("migrate-jscodeshift-runner-to-rust", output),
            {
                "astra-generate-migrate-jscodeshift-runner-to-rust-openhands-a",
                "astra-generate-migrate-jscodeshift-runner-to-rust-openhands-b",
            },
        )

    def test_state_has_all_jobs_pending(self) -> None:
        job = QueueJob("job-1", "glm-5.2", "medium", "prod", 1)
        state = state_template(4, [job])
        self.assertEqual(state["max_concurrency"], 4)
        self.assertEqual(state["jobs"]["job-1"]["status"], "pending")
        self.assertIsNone(state["jobs"]["job-1"]["run_id"])

    def test_nested_lifecycle_files_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            candidate = Path(raw) / "candidate"
            setup = candidate / "codebase/app-setup"
            setup.mkdir(parents=True)
            for relative in ("manifest.json", "build.sh", "reset.sh", "start.sh"):
                (setup / relative).write_text("{}\n", encoding="utf-8")
            self.assertEqual(len(lifecycle_files(candidate)), 4)

    def test_latest_activity_ignores_runtime_cache_directories(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw)
            (run_dir / "candidate/.cargo-target").mkdir(parents=True)
            (run_dir / "candidate/.cargo-target/old").write_text("old", encoding="utf-8")
            source = run_dir / "candidate/src.rs"
            source.write_text("new", encoding="utf-8")
            self.assertGreaterEqual(latest_activity_time(run_dir), source.stat().st_mtime)


if __name__ == "__main__":
    unittest.main()
