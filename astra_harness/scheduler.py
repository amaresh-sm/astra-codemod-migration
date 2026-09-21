"""Queue isolated OpenHands candidate generations without exceeding concurrency."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE_FILE = REPOSITORY_ROOT / "config/candidate-generation-queue.json"
DEFAULT_RUNS_ROOT = REPOSITORY_ROOT / "benchmarking-candidates"
DEFAULT_STATE_FILE = DEFAULT_RUNS_ROOT / ".generation-scheduler-state.json"
DEFAULT_ENV_ROOT = REPOSITORY_ROOT.parent / "hackerrank-openhands-gateway"
GENERATION_TIMEOUT_SECONDS = 21_600
TMPFS_SIZE = "3g"
STALE_CHECK_INTERVAL_SECONDS = 15 * 60
STALE_AFTER_SECONDS = 20 * 60
RUNTIME_CACHE_DIRS = frozenset({".cargo-home", ".cargo-target", ".tmp", ".yarn-cache", "node_modules", "target", ".git"})
LIFECYCLE_FILES = ("app-setup/manifest.json", "app-setup/build.sh", "app-setup/reset.sh", "app-setup/start.sh")


@dataclass(frozen=True)
class QueueJob:
    """One ordered candidate-generation request."""

    job_id: str
    model: str
    reasoning: str
    environment: str
    sequence: int

    @property
    def env_file(self) -> Path:
        return DEFAULT_ENV_ROOT / f".{self.environment}.env"


def slug(value: str) -> str:
    """Convert a model or label into a stable run-id component."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def load_queue(path: Path) -> tuple[int, list[QueueJob]]:
    """Load and validate the ordered queue definition."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("unsupported candidate-generation queue version")
    max_concurrency = payload.get("max_concurrency", 4)
    if not isinstance(max_concurrency, int) or max_concurrency < 1:
        raise ValueError("max_concurrency must be a positive integer")
    jobs = []
    seen: set[str] = set()
    for sequence, item in enumerate(payload.get("jobs", []), start=1):
        if not isinstance(item, dict):
            raise ValueError(f"queue job {sequence} is not an object")
        job_id = item.get("id")
        model = item.get("model")
        reasoning = item.get("reasoning")
        environment = item.get("environment")
        if not all(isinstance(value, str) and value for value in (job_id, model, reasoning, environment)):
            raise ValueError(f"queue job {sequence} has missing string fields")
        if job_id in seen:
            raise ValueError(f"duplicate queue job id: {job_id}")
        if reasoning not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError(f"unsupported reasoning value for {job_id}: {reasoning}")
        if environment not in {"dev", "prod"}:
            raise ValueError(f"environment must be dev or prod for {job_id}")
        seen.add(job_id)
        jobs.append(QueueJob(job_id, model, reasoning, environment, sequence))
    return max_concurrency, jobs


def run_id_for(job: QueueJob, date: str | None = None) -> str:
    """Return a stable readable run id for a queue job."""
    day = date or datetime.now(timezone.utc).strftime("%Y%m%d")
    return (
        f"openhands-{slug(job.model)}-{job.reasoning}-{job.environment}-"
        f"{day}-q{job.sequence:02d}"
    )


def container_name(task_id: str, run_id: str) -> str:
    """Match the container name emitted by ``astra_harness.generate``."""
    return f"astra-generate-{task_id}-{run_id}".replace("_", "-")


def live_generation_containers(task_id: str, docker_output: str) -> set[str]:
    """Extract live generation containers for this task from ``docker ps`` output."""
    prefix = f"astra-generate-{task_id}-".replace("_", "-")
    return {
        line.strip()
        for line in docker_output.splitlines()
        if line.strip().startswith(prefix)
    }


def latest_activity_time(run_dir: Path) -> float | None:
    """Return the newest mtime from retained run output and candidate files."""
    newest: float | None = None
    for root_name in ("candidate", ".openhands-output", "logs"):
        root = run_dir / root_name
        if not root.exists():
            continue
        for current, directories, files in os.walk(root):
            directories[:] = [name for name in directories if name not in RUNTIME_CACHE_DIRS]
            for name in files:
                path = Path(current) / name
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                newest = modified if newest is None else max(newest, modified)
    return newest


def lifecycle_files(candidate: Path) -> list[Path]:
    """Return lifecycle files from either supported candidate layout."""
    roots = [candidate]
    nested = candidate / "codebase"
    if nested.is_dir():
        roots.append(nested)
    for root in roots:
        files = [root / relative for relative in LIFECYCLE_FILES]
        if all(path.is_file() for path in files):
            return files
    return []


def copy_candidate_snapshot(candidate: Path, destination: Path) -> dict[str, object]:
    """Best-effort copy of the candidate before stale-container removal."""
    copied = 0
    errors: list[str] = []
    if not candidate.is_dir():
        return {"source_exists": False, "files_copied": 0, "errors": ["candidate directory is missing"]}
    for current, directories, files in os.walk(candidate):
        directories[:] = [name for name in directories if name not in RUNTIME_CACHE_DIRS]
        relative = Path(current).relative_to(candidate)
        target = destination / relative
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            source = Path(current) / name
            target_file = target / name
            try:
                if source.is_symlink():
                    target_file.write_text(os.readlink(source), encoding="utf-8")
                else:
                    shutil.copy2(source, target_file)
                copied += 1
            except OSError as exc:
                errors.append(f"{source}: {exc}")
    return {"source_exists": True, "files_copied": copied, "errors": errors}


def has_completed_event(run_dir: Path) -> bool:
    """Detect a completed OpenHands session in the retained event stream."""
    events = run_dir / ".openhands-output" / "events.jsonl"
    if not events.is_file():
        return False
    try:
        for line in events.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                if json.loads(line).get("event_type") == "run_completed":
                    return True
            except json.JSONDecodeError:
                continue
    except OSError:
        return False
    return False


def cleanup_stale_container(
    task_id: str,
    container: str,
    runs_root: Path,
    now: float | None = None,
    stale_after_seconds: float = STALE_AFTER_SECONDS,
) -> dict[str, object] | None:
    """Snapshot and remove one container that has had no retained activity."""
    prefix = f"astra-generate-{task_id}-".replace("_", "-")
    if not container.startswith(prefix):
        return None
    run_id = container[len(prefix):]
    run_dir = runs_root / run_id
    activity = latest_activity_time(run_dir)
    current = time.time() if now is None else now
    if activity is not None and current - activity < stale_after_seconds:
        return None

    snapshot = run_dir / "stale-container-snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    candidate = run_dir / "candidate"
    copy_result = copy_candidate_snapshot(candidate, snapshot / "candidate")
    lifecycle = [str(path.relative_to(candidate)) for path in lifecycle_files(candidate)] if candidate.exists() else []
    log_result = subprocess.run(
        ["docker", "logs", container], capture_output=True, text=True, check=False
    )
    (snapshot / "container.log").write_text(
        (log_result.stdout or "") + (log_result.stderr or ""), encoding="utf-8"
    )
    completed = has_completed_event(run_dir)
    remove_result = subprocess.run(
        ["docker", "rm", "--force", container], capture_output=True, text=True, check=False
    )
    report = {
        "container": container,
        "run_id": run_id,
        "activity_age_seconds": None if activity is None else round(current - activity, 3),
        "completed_event": completed,
        "lifecycle_files": lifecycle,
        "candidate_snapshot": str((snapshot / "candidate").relative_to(run_dir)),
        "copy": copy_result,
        "container_log": str((snapshot / "container.log").relative_to(run_dir)),
        "removed": remove_result.returncode == 0,
        "remove_error": remove_result.stderr.strip() if remove_result.returncode else None,
        "cleaned_at": datetime.now(timezone.utc).isoformat(),
    }
    (snapshot / "cleanup.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    metadata_path = run_dir / "metadata.json"
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["status"] = "completed" if completed else "stale_cleaned"
            if completed:
                metadata["exit_code"] = 0
            metadata["container_cleaned"] = report["removed"]
            metadata["stale_cleanup"] = {
                "snapshot": report["candidate_snapshot"],
                "lifecycle_files": bool(lifecycle),
                "activity_age_seconds": report["activity_age_seconds"],
            }
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            report["metadata_update"] = "failed"
    return report


def state_template(max_concurrency: int, jobs: list[QueueJob]) -> dict:
    """Create persistent state while keeping queue order explicit."""
    return {
        "version": 1,
        "max_concurrency": max_concurrency,
        "jobs": {
            job.job_id: {
                "sequence": job.sequence,
                "model": job.model,
                "reasoning": job.reasoning,
                "environment": job.environment,
                "status": "pending",
                "run_id": None,
            }
            for job in jobs
        },
    }


def atomic_write_json(path: Path, payload: dict) -> None:
    """Persist scheduler state without leaving a partially written state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Queue OpenHands candidate generations")
    parser.add_argument("--task", type=Path, default=Path("tasks"))
    parser.add_argument("--queue-file", type=Path, default=DEFAULT_QUEUE_FILE)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--once", action="store_true", help="perform one scheduling pass and exit")
    return parser.parse_args()


class Scheduler:
    """Watch live containers and start the next queue item when a slot opens."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.max_concurrency, self.jobs = load_queue(args.queue_file.resolve())
        self.state = self._load_state()
        self.processes: dict[str, subprocess.Popen] = {}
        self.task_id = self._task_id()
        self.log_dir = args.runs_root.resolve() / ".generation-scheduler"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.last_stale_check = 0.0

    def _task_id(self) -> str:
        task_toml = self.args.task.resolve() / "task.toml"
        if task_toml.is_file():
            import tomllib

            value = tomllib.loads(task_toml.read_text(encoding="utf-8")).get("id")
            if isinstance(value, str) and value:
                return value
        return self.args.task.resolve().name

    def _load_state(self) -> dict:
        if self.args.state_file.is_file():
            state = json.loads(self.args.state_file.read_text(encoding="utf-8"))
            known = state.setdefault("jobs", {})
            for job in self.jobs:
                known.setdefault(
                    job.job_id,
                    state_template(self.max_concurrency, [job])["jobs"][job.job_id],
                )
            state["max_concurrency"] = self.max_concurrency
            return state
        return state_template(self.max_concurrency, self.jobs)

    def _docker_names(self) -> set[str] | None:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            self.state["last_error"] = "docker ps failed: " + (result.stderr.strip() or "unknown error")
            return None
        return live_generation_containers(self.task_id, result.stdout)

    def _active_count(self, docker_names: set[str]) -> int:
        active = set(docker_names)
        for run_id in self.processes:
            if container_name(self.task_id, run_id) not in active:
                active.add(run_id)
        return len(active)

    def _next_pending(self) -> QueueJob | None:
        for job in self.jobs:
            record = self.state["jobs"][job.job_id]
            if record["status"] == "pending":
                return job
        return None

    def _command(self, job: QueueJob, run_id: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "astra_harness.generate",
            "--task",
            str(self.args.task),
            "--provider",
            "openhands",
            "--model",
            job.model,
            "--reasoning",
            job.reasoning,
            "--run-id",
            run_id,
            "--runs-root",
            str(self.args.runs_root),
            "--openhands-env-file",
            str(job.env_file),
            "--tmpfs-size",
            TMPFS_SIZE,
            "--timeout-seconds",
            str(GENERATION_TIMEOUT_SECONDS),
        ]

    def _launch_one(self, job: QueueJob) -> None:
        record = self.state["jobs"][job.job_id]
        run_id = record["run_id"] or run_id_for(job)
        log_path = self.log_dir / f"{job.sequence:02d}-{job.job_id}.log"
        log = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            self._command(job, run_id),
            cwd=REPOSITORY_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes[run_id] = process
        record.update(
            {
                "status": "running",
                "run_id": run_id,
                "pid": process.pid,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.state.pop("last_error", None)
        atomic_write_json(self.args.state_file, self.state)

    def _reap(self) -> None:
        for run_id, process in list(self.processes.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            record = next(
                item for item in self.state["jobs"].values() if item.get("run_id") == run_id
            )
            record["status"] = "completed" if return_code == 0 else "failed"
            record["exit_code"] = return_code
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            del self.processes[run_id]
        atomic_write_json(self.args.state_file, self.state)

    def _cleanup_stale(self, docker_names: set[str]) -> list[dict[str, object]]:
        """Run the guarded stale-container sweep and persist its results."""
        if time.monotonic() - self.last_stale_check < STALE_CHECK_INTERVAL_SECONDS:
            return []
        self.last_stale_check = time.monotonic()
        cleaned = []
        for container in sorted(docker_names):
            report = cleanup_stale_container(self.task_id, container, self.args.runs_root.resolve())
            if report is not None and report.get("removed"):
                cleaned.append(report)
                print(json.dumps({"stale_cleanup": report}), flush=True)
        return cleaned

    def pass_once(self) -> dict:
        """Reap finished children and fill available global slots in queue order."""
        self._reap()
        docker_names = self._docker_names()
        if docker_names is None:
            atomic_write_json(self.args.state_file, self.state)
            return {"active": None, "launched": []}
        self._cleanup_stale(docker_names)
        docker_names = self._docker_names() or set()
        launched = []
        while self._active_count(docker_names) < self.max_concurrency:
            job = self._next_pending()
            if job is None:
                break
            self._launch_one(job)
            launched.append(job.job_id)
        atomic_write_json(self.args.state_file, self.state)
        return {"active": self._active_count(docker_names), "launched": launched}

    def run(self) -> int:
        """Run until interrupted, or perform one pass for tests/inspection."""
        while True:
            result = self.pass_once()
            print(json.dumps(result), flush=True)
            if self.args.once:
                return 0
            time.sleep(self.args.poll_seconds)


def main() -> int:
    return Scheduler(parse_args()).run()


if __name__ == "__main__":
    raise SystemExit(main())
