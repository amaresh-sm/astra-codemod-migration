"""Run a task's private verifier against one candidate in Docker."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tomllib
import time
from datetime import datetime, timezone
from pathlib import Path

from .redaction import redact_tree


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a candidate in an isolated container")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True, help="Directory where reports and metadata are written")
    parser.add_argument("--verifier-command", required=True)
    parser.add_argument("--image", default="astra-verifier:latest")
    parser.add_argument("--runtime-image", default="astra-candidate-runtime:latest")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=14_400)
    return parser.parse_args()


def docker_exec(
    runtime_name: str, command: list[str], *, cwd: str = "/workspace", stdout: object | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run an untrusted manifest command only inside the candidate runtime."""

    return subprocess.run(
        ["docker", "exec", "--workdir", cwd, runtime_name, *command],
        stdout=stdout,
        stderr=subprocess.STDOUT if stdout is not None else None,
        check=False,
        timeout=timeout,
    )


def load_candidate_manifest(candidate: Path) -> tuple[dict[str, list[str]], str]:
    """Read the public lifecycle handoff without importing verifier material."""

    path = candidate / "app-setup" / "manifest.json"
    if not path.is_file():
        legacy = candidate / "verification" / "manifest.json"
        if legacy.is_file():
            path = legacy
        else:
            raise SystemExit(f"candidate manifest is missing: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid candidate manifest: {exc}") from exc
    commands = raw.get("commands") if isinstance(raw, dict) else None
    if not isinstance(commands, dict):
        raise SystemExit("manifest must contain a commands object")
    selected: dict[str, list[str]] = {}
    for name in ("build", "reset", "start"):
        value = commands.get(name)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
            raise SystemExit(f"manifest commands.{name} must be a non-empty argument array")
        selected[name] = value
    return selected, str(path.relative_to(candidate))


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def start_runtime_candidate(runtime_name: str, command: list[str], log_path: Path) -> subprocess.Popen[bytes]:
    """Start the foreground candidate command and retain its in-container PID."""

    return subprocess.Popen(
        [
            "docker", "exec", "--workdir", "/workspace", runtime_name,
            "sh", "-c", 'echo "$$" > /tmp/astra-candidate.pid; exec "$@"',
            "astra-candidate-start", *command,
        ],
        stdout=log_path.open("ab"),
        stderr=subprocess.STDOUT,
    )


def stop_runtime_candidate(runtime_name: str, process: subprocess.Popen[bytes] | None) -> None:
    """Stop precisely the candidate app rather than every process in its container."""

    subprocess.run(
        [
            "docker", "exec", runtime_name, "sh", "-c",
            'if [ -r /tmp/astra-candidate.pid ]; then kill -TERM "$(cat /tmp/astra-candidate.pid)" 2>/dev/null || true; rm -f /tmp/astra-candidate.pid; fi',
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    stop_process(process)


def wait_for_runtime_database(runtime_name: str, timeout: int) -> None:
    """Wait for the disposable database before a manifest reset touches it."""

    deadline = time.monotonic() + min(timeout, 60)
    while time.monotonic() < deadline:
        probe = subprocess.run(
            [
                "docker", "exec", "--env", "PGPASSWORD=arena", runtime_name,
                "psql", "--host", "127.0.0.1", "--username", "arena", "--dbname", "arena",
                "--command", "SELECT 1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if probe.returncode == 0:
            return
        time.sleep(0.25)
    raise RuntimeError("candidate runtime database did not become ready")


def wait_for_restart_request(
    verifier_process: subprocess.Popen[bytes], *, control_dir: Path, runtime_name: str, start_command: list[str], logs: Path,
    candidate_process: subprocess.Popen[bytes], timeout: int,
) -> subprocess.Popen[bytes]:
    """Perform only verifier-requested restarts, without sharing its files with the app."""

    handled: set[str] = set()
    deadline = time.monotonic() + timeout
    while verifier_process.poll() is None:
        if time.monotonic() > deadline:
            verifier_process.kill()
            raise TimeoutError("verifier timed out")
        for request in control_dir.glob("restart-*.json"):
            label = request.stem.removeprefix("restart-")
            if label in handled:
                continue
            stop_runtime_candidate(runtime_name, candidate_process)
            candidate_process = start_runtime_candidate(runtime_name, start_command, logs / "candidate.start.log")
            (control_dir / f"restart-{label}.ack").write_text("ok\n", encoding="utf-8")
            handled.add(label)
        time.sleep(0.2)
    return candidate_process


def locate_verifier(task_dir: Path) -> Path:
    """Resolve the task-private verifier without exposing it to candidates."""
    nested = task_dir / "verifier"
    if nested.is_dir():
        return nested
    if task_dir.name == "tasks":
        flat_verifier = task_dir.parent / "verifier"
        if flat_verifier.is_dir():
            return flat_verifier
    repository_verifier = task_dir.parents[1] / "verifier" / task_dir.name
    if repository_verifier.is_dir():
        return repository_verifier
    raise SystemExit(f"private verifier is missing for task: {task_dir}")


def task_identifier(task_dir: Path) -> str:
    """Return the stable task id from task.toml for flat task packages."""
    try:
        metadata = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return task_dir.name
    value = metadata.get("id")
    return value if isinstance(value, str) and value else task_dir.name


def run(args: argparse.Namespace) -> int:
    task_dir = args.task.resolve()
    candidate = args.candidate.resolve()
    verifier = locate_verifier(task_dir).resolve()
    public = (task_dir / "public").resolve()
    run_dir = args.run.resolve()
    if not candidate.is_dir():
        raise SystemExit(f"candidate directory does not exist: {candidate}")
    if not verifier.is_dir():
        raise SystemExit(f"task must contain private verifier/: {verifier}")
    run_dir.mkdir(parents=True, exist_ok=True)
    logs = run_dir / "logs"
    logs.mkdir(exist_ok=True)
    reports = run_dir / "reports"
    reports.mkdir(exist_ok=True)

    task_id = task_identifier(task_dir)
    name = f"astra-verify-{task_id}-{run_dir.name}".replace("_", "-")
    runtime_name = f"{name}-runtime"
    commands, manifest_path = load_candidate_manifest(candidate)
    runtime_args = [
        "docker", "run", "--detach", "--rm", "--name", runtime_name,
        "--cap-drop", "NET_RAW", "--security-opt", "no-new-privileges",
        "--mount", f"type=bind,src={candidate},dst=/workspace",
        args.runtime_image,
    ]
    docker_args = [
        "docker", "run", "--rm", "--name", name,
        "--network", f"container:{runtime_name}",
        "--mount", f"type=bind,src={candidate},dst=/input/candidate,readonly",
        "--mount", f"type=bind,src={verifier},dst=/input/verifier,readonly",
    ]
    if public.is_dir():
        # The verifier needs frozen public contracts as grader-owned input.
        # Mounting the task copy separately prevents a candidate from changing
        # its own exported handoff and thereby changing the comparison target.
        docker_args += ["--mount", f"type=bind,src={public},dst=/input/public,readonly"]
    docker_args += [
        "--mount", f"type=bind,src={reports},dst=/output",
        "--env", f"VERIFIER_COMMAND={args.verifier_command} --candidate /input/candidate --output /output --external-lifecycle",
        "--env", "ASTRA_EXTERNAL_LIFECYCLE=1",
        "--env", "ASTRA_CONTROL_DIR=/output/control",
        args.image,
    ]
    if args.env_file:
        docker_args[2:2] = ["--env-file", str(args.env_file.resolve())]

    metadata_path = run_dir / "verification.json"
    metadata: dict[str, object] = {
        "task_id": task_id,
        "candidate_id": candidate.parent.name if candidate.name == "candidate" else candidate.name,
        "workspace": "<candidate-workspace>",
        "image": args.image,
        "runtime_image": args.runtime_image,
        "manifest": manifest_path,
        "started_at": utc_now(),
        "status": "running",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    started = time.monotonic()
    runtime_started = False
    candidate_process: subprocess.Popen[bytes] | None = None
    try:
        subprocess.run(runtime_args, check=True, stdout=subprocess.DEVNULL)
        runtime_started = True
        wait_for_runtime_database(runtime_name, args.timeout_seconds)
        with (logs / "candidate.build.log").open("wb") as log:
            build_result = docker_exec(runtime_name, commands["build"], stdout=log, timeout=args.timeout_seconds)
        if build_result.returncode != 0:
            raise RuntimeError("candidate build command failed")
        with (logs / "candidate.reset.log").open("wb") as log:
            reset_result = docker_exec(runtime_name, commands["reset"], stdout=log, timeout=args.timeout_seconds)
        if reset_result.returncode != 0:
            raise RuntimeError("candidate reset command failed")
        # Reset commands are allowed to remove generated build artifacts (for
        # example, ``cargo clean``). Rebuild after reset so the private verifier
        # can execute the candidate from its separate, toolchain-free container.
        with (logs / "candidate.rebuild.log").open("wb") as log:
            rebuild_result = docker_exec(runtime_name, commands["build"], stdout=log, timeout=args.timeout_seconds)
        if rebuild_result.returncode != 0:
            raise RuntimeError("candidate rebuild command failed")
        candidate_process = start_runtime_candidate(runtime_name, commands["start"], logs / "candidate.start.log")
        control_dir = reports / "control"
        control_dir.mkdir(exist_ok=True)
        result = subprocess.Popen(
            docker_args,
            stdout=(logs / "verifier.stdout.log").open("w"),
            stderr=(logs / "verifier.stderr.log").open("w"),
            env={key: value for key, value in os.environ.items() if key != "VERIFIER_COMMAND"},
        )
        # The task verifier asks for a restart through a host-only output
        # handshake. Candidate code never receives that directory.
        candidate_process = wait_for_restart_request(
            result,
            control_dir=control_dir,
            runtime_name=runtime_name,
            start_command=commands["start"],
            logs=logs,
            candidate_process=candidate_process,
            timeout=args.timeout_seconds,
        )
        metadata["status"] = "passed" if result.returncode == 0 else "failed"
        metadata["exit_code"] = result.returncode
    except subprocess.TimeoutExpired:
        metadata["status"] = "timed_out"
        metadata["exit_code"] = 124
    except OSError as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        metadata["exit_code"] = 127
    except (RuntimeError, subprocess.CalledProcessError, TimeoutError) as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        metadata["exit_code"] = 1
    finally:
        if runtime_started:
            stop_runtime_candidate(runtime_name, candidate_process)
        else:
            stop_process(candidate_process)
        if runtime_started:
            subprocess.run(["docker", "rm", "--force", runtime_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    metadata["finished_at"] = utc_now()
    metadata["duration_seconds"] = round(time.monotonic() - started, 3)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    redact_tree(
        run_dir,
        {
            candidate: "<candidate-workspace>",
            task_dir: "<task-package>",
            verifier: "<private-verifier>",
            run_dir: "<run-directory>",
        },
    )
    print(run_dir)
    return 0 if metadata["status"] == "passed" else 1


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
