"""Run one isolated candidate-generation session."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .providers import build_provider_command
from .telemetry import collect as collect_telemetry
from .telemetry import snapshot_workspace


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a candidate in an isolated container")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--provider", choices=("codex", "openai-compatible", "claude-code"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", choices=("low", "medium", "high", "xhigh", "max"), default="medium")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--image", default="astra-candidate-generation:latest")
    parser.add_argument("--dockerfile", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=None, help="Private provider env file; never commit it")
    parser.add_argument("--auth-file", type=Path, default=None, help="Optional Codex auth.json copied into the container")
    parser.add_argument(
        "--claude-credentials-file",
        type=Path,
        default=None,
        help="Optional Claude Code .credentials.json copied into the container",
    )
    parser.add_argument(
        "--cloud-config-file",
        type=Path,
        default=None,
        help="Optional Codex cloud-policy cache copied into the container",
    )
    parser.add_argument("--ca-cert", type=Path, default=None, help="Optional PEM CA bundle for a TLS-inspecting network")
    parser.add_argument("--timeout-seconds", type=int, default=14_400)
    parser.add_argument("--command", default=None, help="Override the provider CLI command for a custom installation")
    return parser.parse_args()


def ensure_image(args: argparse.Namespace) -> None:
    """Build the generation image when it is missing or lacks the selected CLI."""
    found = subprocess.run(
        ["docker", "image", "inspect", args.image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    required_cli = "claude" if args.provider == "claude-code" else "codex"
    if found.returncode == 0:
        installed = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "sh", args.image, "-lc", f"command -v {required_cli}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if installed.returncode == 0:
            return
    repository_root = Path(__file__).resolve().parents[1]
    dockerfile = (args.dockerfile or repository_root / "environment/candidate-generation/Dockerfile").resolve()
    if not dockerfile.is_file():
        raise SystemExit(f"generation image is missing and Dockerfile was not found: {dockerfile}")
    subprocess.run(
        ["docker", "build", "--tag", args.image, "--file", str(dockerfile), str(repository_root)],
        check=True,
    )


def prepare_workspace(task_dir: Path, run_dir: Path) -> Path:
    """Create the only host directory visible to the generation container."""
    instruction = task_dir / "instruction.md"
    public = task_dir / "public"
    if not instruction.is_file() or not public.is_dir():
        raise SystemExit("task must contain instruction.md and public/")
    workspace = run_dir / "candidate"
    workspace.mkdir(parents=True, exist_ok=False)
    shutil.copy2(instruction, workspace / "INSTRUCTION.md")
    shutil.copytree(public, workspace, dirs_exist_ok=True)
    return workspace


def task_identifier(task_dir: Path) -> str:
    """Use task.toml's stable ID for run names, including flat task branches."""
    try:
        metadata = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return task_dir.name
    value = metadata.get("id")
    return value if isinstance(value, str) and value else task_dir.name


def run(args: argparse.Namespace) -> int:
    task_dir = args.task.resolve()
    task_id = task_identifier(task_dir)
    run_id = args.run_id or f"{args.provider}-{int(time.time())}"
    run_dir = (args.runs_root / task_id / run_id).resolve()
    logs = run_dir / "logs"
    run_dir.mkdir(parents=True, exist_ok=False)
    logs.mkdir()
    workspace = prepare_workspace(task_dir, run_dir)
    workspace_before = snapshot_workspace(workspace)
    ensure_image(args)

    provider_command = build_provider_command(args.provider, args.model, args.reasoning)
    generation_command = args.command or provider_command.command
    container_name = f"astra-generate-{task_id}-{run_id}".replace("_", "-")
    docker_args = ["docker", "run", "--detach", "--name", container_name,
                   "--mount", f"type=bind,src={workspace},dst=/workspace"]
    if args.env_file:
        docker_args += ["--env-file", str(args.env_file.resolve())]
    if args.ca_cert:
        docker_args += ["--mount", f"type=bind,src={args.ca_cert.resolve()},dst=/tmp/provider-ca.pem,readonly",
                        "--env", "SSL_CERT_FILE=/tmp/provider-ca.pem"]
    docker_args += ["--entrypoint", "sleep", args.image, "infinity"]

    metadata = {
        "task_id": task_id,
        "run_id": run_id,
        "provider": args.provider,
        "model": args.model,
        "reasoning": args.reasoning,
        "image": args.image,
        "started_at": utc_now(),
        "status": "running",
        "mounts": ["candidate workspace:rw"],
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    started = time.monotonic()
    container_started = False
    try:
        subprocess.run(docker_args, check=True, stdout=subprocess.DEVNULL)
        container_started = True
        if args.provider == "codex":
            auth_file = args.auth_file or (Path.home() / ".codex/auth.json")
            if auth_file.is_file():
                subprocess.run(["docker", "exec", "--user", "root", container_name, "mkdir", "-p", "/home/runner/.codex"], check=True)
                subprocess.run(["docker", "cp", str(auth_file.resolve()), f"{container_name}:/home/runner/.codex/auth.json"], check=True)
                subprocess.run(["docker", "exec", "--user", "root", container_name, "chown", "-R", "runner:runner", "/home/runner/.codex"], check=True)
                subprocess.run(["docker", "exec", "--user", "root", container_name, "chmod", "0600", "/home/runner/.codex/auth.json"], check=True)
            if args.cloud_config_file:
                cloud_config_file = args.cloud_config_file.resolve()
                if not cloud_config_file.is_file():
                    raise SystemExit(f"Codex cloud-policy cache was not found: {cloud_config_file}")
                subprocess.run(["docker", "exec", "--user", "root", container_name, "mkdir", "-p", "/home/runner/.codex"], check=True)
                subprocess.run(
                    [
                        "docker",
                        "cp",
                        str(cloud_config_file),
                        f"{container_name}:/home/runner/.codex/cloud-config-bundle-cache.json",
                    ],
                    check=True,
                )
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        "--user",
                        "root",
                        container_name,
                        "chown",
                        "runner:runner",
                        "/home/runner/.codex/cloud-config-bundle-cache.json",
                    ],
                    check=True,
                )
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        "--user",
                        "root",
                        container_name,
                        "chmod",
                        "0600",
                        "/home/runner/.codex/cloud-config-bundle-cache.json",
                    ],
                    check=True,
                )
        if args.provider == "claude-code":
            credentials_file = args.claude_credentials_file or (Path.home() / ".claude/.credentials.json")
            if credentials_file.is_file():
                subprocess.run(
                    ["docker", "exec", "--user", "root", container_name, "mkdir", "-p", "/home/runner/.claude"],
                    check=True,
                )
                subprocess.run(
                    ["docker", "cp", str(credentials_file.resolve()), f"{container_name}:/home/runner/.claude/.credentials.json"],
                    check=True,
                )
                subprocess.run(
                    ["docker", "exec", "--user", "root", container_name, "chown", "-R", "runner:runner", "/home/runner/.claude"],
                    check=True,
                )
                subprocess.run(
                    ["docker", "exec", "--user", "root", container_name, "chmod", "0600", "/home/runner/.claude/.credentials.json"],
                    check=True,
                )
        prompt_stream = (
            (workspace / "INSTRUCTION.md").open("r")
            if args.provider in {"codex", "openai-compatible", "claude-code"}
            else None
        )
        with (logs / "stdout.log").open("w") as stdout, (logs / "stderr.log").open("w") as stderr:
            result = subprocess.run(
                ["docker", "exec", "--interactive", "--user", "runner", container_name,
                 "sh", "-lc", f"cd /workspace && {generation_command}"],
                check=False, stdin=prompt_stream, stdout=stdout, stderr=stderr, timeout=args.timeout_seconds, text=True,
            )
        if prompt_stream:
            prompt_stream.close()
        metadata["status"] = "completed" if result.returncode == 0 else "failed"
        metadata["exit_code"] = result.returncode
    except subprocess.TimeoutExpired:
        metadata["status"] = "timed_out"
        metadata["exit_code"] = 124
    except (OSError, subprocess.CalledProcessError) as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        metadata["exit_code"] = 127
    finally:
        if container_started:
            subprocess.run(["docker", "rm", "--force", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    metadata["finished_at"] = utc_now()
    metadata["duration_seconds"] = round(time.monotonic() - started, 3)
    metadata["container_cleaned"] = not container_started or subprocess.run(
        ["docker", "container", "inspect", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    ).returncode != 0
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    telemetry = collect_telemetry(workspace, workspace_before, logs / "stdout.log")
    telemetry["duration_seconds"] = metadata["duration_seconds"]
    telemetry["started_at"] = metadata["started_at"]
    telemetry["finished_at"] = metadata["finished_at"]
    (run_dir / "telemetry.json").write_text(json.dumps(telemetry, indent=2) + "\n")
    print(run_dir)
    return 0 if metadata["status"] == "completed" else 1


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
