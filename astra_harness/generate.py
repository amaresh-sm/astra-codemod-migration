"""Run one isolated candidate-generation session."""

from __future__ import annotations

import argparse
import json
import os
import re
import re
import shlex
import shutil
import subprocess
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .providers import build_provider_command
from .telemetry import collect as collect_telemetry
from .telemetry import snapshot_workspace


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE_ROOT = REPOSITORY_ROOT / "benchmarking-candidates"
DEFAULT_OPENHANDS_ENV_FILE = REPOSITORY_ROOT.parent / "hackerrank-openhands-gateway" / ".env"
OPENHANDS_ENVIRONMENT_KEYS = {
    "ASTRA_GATEWAY_API_KEY",
    "ASTRA_GATEWAY_BASE_URL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
}
OPENHANDS_RUNTIME_ENVIRONMENT = {
    "CARGO_HOME": "/workspace/.cargo-home",
    "CARGO_TARGET_DIR": "/workspace/.cargo-target",
    "TMPDIR": "/workspace/.tmp",
    "YARN_CACHE_FOLDER": "/workspace/.yarn-cache",
}
OPENHANDS_REASONING_OPTIONS = ("none", "minimal", "low", "medium", "high", "xhigh", "ultra", "max")
MIN_PREFLIGHT_FREE_KB = 512 * 1024
MIN_PREFLIGHT_FREE_INODES = 10_000


class GenerationPreflightError(RuntimeError):
    """Raised when the isolated generation container is not usable."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a candidate in an isolated container")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--provider", choices=("codex", "openai-compatible", "claude-code", "openhands"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", choices=("low", "medium", "high", "xhigh", "max"), default="medium")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=DEFAULT_CANDIDATE_ROOT,
        help="Root directory for generated candidates and run artifacts; each run is a direct child",
    )
    parser.add_argument("--image", default="astra-candidate-generation:latest")
    parser.add_argument("--dockerfile", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=None, help="Private provider env file; legacy alias for OpenHands")
    parser.add_argument(
        "--openhands-env-file",
        type=Path,
        default=None,
        help="Private OpenHands env file; defaults to ../hackerrank-openhands-gateway/.env",
    )
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
    parser.add_argument(
        "--tmpfs-size",
        default="1g",
        help="Size of the OpenHands container /tmp tmpfs (for example: 1g or 3g)",
    )
    parser.add_argument("--timeout-seconds", type=int, default=14_400)
    parser.add_argument("--command", default=None, help="Override the provider CLI command for a custom installation")
    return parser.parse_args()


def validate_tmpfs_size(value: str) -> str:
    """Validate a Docker-compatible tmpfs size before adding it to docker args."""
    if not re.fullmatch(r"[1-9][0-9]*(?:[bkmgtepiBKMGTEPI](?:b|i)?|[bB])", value):
        raise SystemExit("--tmpfs-size must be a positive Docker size such as 1g or 3g")
    return value


def ensure_image(args: argparse.Namespace) -> None:
    """Build the generation image when it is missing or lacks the selected CLI."""
    found = subprocess.run(
        ["docker", "image", "inspect", args.image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    required_tools = {
        "claude-code": "claude",
        "openhands": "hackerrank-openhands",
    }.get(args.provider, "codex")
    if args.provider == "openhands":
        required_tools = f"{required_tools} rsync tmux"
    version_check = ""
    if args.provider == "openhands":
        expected_version = gateway_package_version()
        version_check = (
            " && test \"$(python3.12 -c "
            + shlex.quote(
                "import importlib.metadata as m; "
                "print(m.version('hackerrank-openhands-gateway'))"
            )
            + f")\" = {shlex.quote(expected_version)}"
        )
    if found.returncode == 0:
        installed = subprocess.run(
            [
                "docker", "run", "--rm", "--entrypoint", "sh", args.image, "-lc",
                f"for tool in {required_tools}; do command -v \"$tool\"; done "
                f"&& getent passwd runner{version_check}",
            ],
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


def gateway_package_version() -> str:
    """Read the vendored reusable Gateway package version used by the image."""
    package_file = REPOSITORY_ROOT / "vendor" / "hackerrank-openhands-gateway" / "pyproject.toml"
    try:
        metadata = tomllib.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GenerationPreflightError(f"Gateway package metadata is unavailable: {package_file}") from exc
    version = metadata.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise GenerationPreflightError(f"Gateway package version is missing: {package_file}")
    return version


def openhands_runtime_environment() -> dict[str, str]:
    """Return writable, run-local paths used by OpenHands and candidate builds."""
    return dict(OPENHANDS_RUNTIME_ENVIRONMENT)


def openhands_preflight_script(model: str, reasoning: str) -> str:
    """Build a secret-free shell/Python preflight for an OpenHands container."""
    model_arg = shlex.quote(model)
    reasoning_arg = shlex.quote(reasoning)
    return f'''set -eu
for tool in cargo node yarn hackerrank-openhands rsync tmux
do
  if ! command -v "$tool" >/dev/null 2>&1
  then
    echo "missing required tool: $tool" >&2
    exit 20
  fi
done
for directory in /workspace/.cargo-home /workspace/.cargo-target /workspace/.tmp /workspace/.yarn-cache
do
  mkdir -p "$directory"
  if ! test -w "$directory"
  then
    echo "directory is not writable: $directory" >&2
    exit 21
  fi
done
touch /workspace/.tmp/.astra-preflight
rm -f /workspace/.tmp/.astra-preflight
free_kb="$(df -Pk /workspace | awk 'NR == 2 {{ print $4 }}')"
free_inodes="$(df -Pi /workspace | awk 'NR == 2 {{ print $4 }}')"
if ! test "$free_kb" -ge {MIN_PREFLIGHT_FREE_KB}
then
  echo "insufficient workspace space: $free_kb KiB free" >&2
  exit 22
fi
if ! test "$free_inodes" -ge {MIN_PREFLIGHT_FREE_INODES}
then
  echo "insufficient workspace inodes: $free_inodes free" >&2
  exit 23
fi
python3.12 - {model_arg} {reasoning_arg} <<'PY'
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

model, reasoning = sys.argv[1:]
supported_reasoning = {OPENHANDS_REASONING_OPTIONS!r}
if reasoning not in supported_reasoning:
    raise SystemExit("unsupported OpenHands reasoning value: " + reasoning)
env_file = Path("/tmp/openhands.env")
if env_file.is_file():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"ASTRA_GATEWAY_API_KEY", "ASTRA_GATEWAY_BASE_URL", "LLM_API_KEY", "LLM_BASE_URL"}:
            os.environ.setdefault(key, value)
base_url = (os.environ.get("ASTRA_GATEWAY_BASE_URL") or os.environ.get("LLM_BASE_URL") or "").rstrip("/")
api_key = os.environ.get("ASTRA_GATEWAY_API_KEY") or os.environ.get("LLM_API_KEY")
if not base_url:
    raise SystemExit("Gateway base URL is not configured")
if not api_key:
    raise SystemExit("Gateway API key is not configured")
request = urllib.request.Request(
    base_url + "/models",
    headers=dict(Authorization="Bearer " + api_key, Accept="application/json"),
)
try:
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
except urllib.error.HTTPError as exc:
    if exc.code not in {404, 405}:
        raise SystemExit("Gateway model catalog check failed with HTTP " + str(exc.code))
    payload = None
    print("Gateway has no /models catalog; model support will be checked by the generation request")
except (urllib.error.URLError, TimeoutError, ValueError) as exc:
    raise SystemExit("Gateway connectivity check failed: " + exc.__class__.__name__)
if payload is not None:
    items = payload.get("data") if isinstance(payload, dict) else None
    model_ids = set(
        str(item.get("id"))
        for item in items
        if isinstance(item, dict) and item.get("id")
    ) if isinstance(items, list) else set()
    accepted = (model, "openai/" + model)
    if not model_ids or not any(item in model_ids for item in accepted):
        raise SystemExit("model is not advertised by Gateway: " + model)
print("preflight ok: model=" + model + " reasoning=" + reasoning + " gateway=" + base_url)
PY
'''


def run_openhands_preflight(container_name: str, model: str, reasoning: str, log_path: Path) -> None:
    """Run and persist the isolated environment/model capability check."""
    result = subprocess.run(
        [
            "docker", "exec", "--user", "runner", container_name,
            "sh", "-lc", openhands_preflight_script(model, reasoning),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        detail = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
        raise GenerationPreflightError(detail)


def cleanup_openhands_runtime(workspace: Path) -> None:
    """Remove harness-owned build/cache directories from completed candidates."""
    for relative in OPENHANDS_RUNTIME_ENVIRONMENT.values():
        path = workspace / Path(relative).relative_to("/workspace")
        shutil.rmtree(path, ignore_errors=True)


def capture_container_diagnostics(container_name: str, logs: Path, started: bool) -> None:
    """Retain Docker state and container output before the container is removed."""
    logs.mkdir(parents=True, exist_ok=True)
    if not started:
        (logs / "container-state.json").write_text(
            json.dumps({"started": False, "status": "not_started"}, indent=2) + "\n",
            encoding="utf-8",
        )
        (logs / "docker.log").write_text("container was not started\n", encoding="utf-8")
        return

    state = subprocess.run(
        ["docker", "inspect", "--format", "{{json .State}}", container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    (logs / "container-state.json").write_text(
        state.stdout or state.stderr or "container state unavailable\n",
        encoding="utf-8",
    )
    output = subprocess.run(
        ["docker", "logs", container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    (logs / "docker.log").write_text(
        (output.stdout or "") + (output.stderr or ""),
        encoding="utf-8",
    )


def preserve_failure_diagnostics(
    run_dir: Path,
    workspace: Path,
    workspace_before: dict[str, str],
    package_output: Path,
) -> None:
    """Persist final workspace evidence and raw OpenHands output for failures."""
    diagnostics = run_dir / "failure-diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    final_files = snapshot_workspace(workspace)
    (diagnostics / "final-workspace-snapshot.json").write_text(
        json.dumps(
            {
                "workspace": str(workspace),
                "initial_file_count": len(workspace_before),
                "final_file_count": len(final_files),
                "files": final_files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if package_output.is_dir():
        shutil.copytree(
            package_output,
            diagnostics / "openhands-output",
            dirs_exist_ok=True,
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


def openhands_environment_file(args: argparse.Namespace) -> Path:
    """Resolve the package-owned OpenHands environment file."""
    return (
        args.openhands_env_file
        or (args.env_file if args.provider == "openhands" else None)
        or DEFAULT_OPENHANDS_ENV_FILE
    ).resolve()


def filtered_openhands_environment(path: Path) -> str:
    """Validate and retain only the four supported Gateway environment keys."""
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SystemExit(f"OpenHands environment file is unavailable: {path}") from exc
    if (
        not path.is_file()
        or path.is_symlink()
        or metadata.st_size == 0
        or metadata.st_size > 64 * 1024
        or metadata.st_mode & 0o077
    ):
        raise SystemExit("OpenHands environment file must be a private, non-empty regular file")

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not match or match.group(1) not in OPENHANDS_ENVIRONMENT_KEYS:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = re.sub(r"[ \t]+#.*$", "", value).strip()
        values[match.group(1)] = value

    if not (values.get("ASTRA_GATEWAY_API_KEY") or values.get("LLM_API_KEY")):
        raise SystemExit("OpenHands environment file must contain ASTRA_GATEWAY_API_KEY or LLM_API_KEY")
    base_url = values.get("ASTRA_GATEWAY_BASE_URL") or values.get("LLM_BASE_URL")
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise SystemExit("OpenHands Gateway base URL must be a credential-free HTTP or HTTPS URL")
    return "".join(f"{key}={value}\n" for key, value in values.items())


def task_identifier(task_dir: Path) -> str:
    """Use task.toml's stable ID for run names, including flat task branches."""
    try:
        metadata = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return task_dir.name
    value = metadata.get("id")
    return value if isinstance(value, str) and value else task_dir.name


def run(args: argparse.Namespace) -> int:
    args.tmpfs_size = validate_tmpfs_size(args.tmpfs_size)
    task_dir = args.task.resolve()
    task_id = task_identifier(task_dir)
    openhands_env = (
        filtered_openhands_environment(openhands_environment_file(args))
        if args.provider == "openhands"
        else None
    )
    run_id = args.run_id or f"{args.provider}-{int(time.time())}"
    # Match the shared benchmark layout: benchmarking-candidates/<run-id>/...
    # The task ID remains in metadata and container names, so it does not need
    # to be repeated as a path segment for this single-task benchmark.
    run_dir = (args.runs_root / run_id).resolve()
    logs = run_dir / "logs"
    run_dir.mkdir(parents=True, exist_ok=False)
    logs.mkdir()
    workspace = prepare_workspace(task_dir, run_dir)
    workspace_before = snapshot_workspace(workspace)
    (logs / "stdout.log").touch()
    (logs / "stderr.log").touch()

    # The reusable OpenHands/Gateway package writes its complete telemetry
    # bundle to the mounted output directory. Keep that output outside the
    # candidate workspace so it cannot be mistaken for an agent edit.
    package_output = run_dir / ".openhands-output"
    if args.provider == "openhands":
        package_output.mkdir(mode=0o777)

    provider_command = build_provider_command(args.provider, args.model, args.reasoning)
    generation_command = args.command or provider_command.command
    container_name = f"astra-generate-{task_id}-{run_id}".replace("_", "-")
    docker_args = ["docker", "run", "--detach", "--name", container_name,
                   "--mount", f"type=bind,src={workspace},dst=/workspace"]
    if args.provider == "openhands":
        docker_args += [
            "--mount", f"type=bind,src={package_output},dst=/output",
            "--env", "CARGO_HOME=/workspace/.cargo-home",
            "--env", "CARGO_TARGET_DIR=/workspace/.cargo-target",
            "--env", "TMPDIR=/workspace/.tmp",
            "--env", "YARN_CACHE_FOLDER=/workspace/.yarn-cache",
            # Keep /tmp available for OpenHands internals while moving build
            # scratch and dependency caches to the writable workspace mount.
            "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={args.tmpfs_size}",
        ]
    if args.env_file and args.provider != "openhands":
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
    container_cleaned = True
    try:
        ensure_image(args)
        subprocess.run(docker_args, check=True, stdout=subprocess.DEVNULL)
        container_started = True
        if args.provider == "openhands":
            # Stream only filtered Gateway settings into the container's
            # ephemeral tmpfs; never bind-mount the host .env file.
            subprocess.run(
                [
                    "docker", "exec", "--interactive", "--user", "runner",
                    container_name, "sh", "-c", "umask 077 && cat > /tmp/openhands.env",
                ],
                input=openhands_env,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            runtime_dirs = " ".join(
                shlex.quote(path) for path in OPENHANDS_RUNTIME_ENVIRONMENT.values()
            )
            subprocess.run(
                [
                    "docker", "exec", "--user", "runner", container_name,
                    "sh", "-lc", f"mkdir -p {runtime_dirs}",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            run_openhands_preflight(
                container_name,
                args.model,
                args.reasoning,
                logs / "preflight.log",
            )
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
    except (OSError, subprocess.CalledProcessError, GenerationPreflightError) as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        metadata["exit_code"] = 127
    finally:
        if metadata["status"] in {"failed", "timed_out"}:
            capture_container_diagnostics(container_name, logs, container_started)
        if container_started:
            subprocess.run(["docker", "rm", "--force", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            container_cleaned = subprocess.run(
                ["docker", "container", "inspect", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode != 0

    if args.provider == "openhands" and metadata["status"] == "completed":
        cleanup_openhands_runtime(workspace)

    if metadata["status"] in {"failed", "timed_out"}:
        preserve_failure_diagnostics(run_dir, workspace, workspace_before, package_output)
        metadata["failure_diagnostics"] = {
            "directory": "failure-diagnostics",
            "final_workspace_snapshot": "failure-diagnostics/final-workspace-snapshot.json",
            "container_state": "logs/container-state.json",
            "docker_log": "logs/docker.log",
        }
    if args.provider == "openhands":
        # Promote the package-owned artifacts to the standard run layout used
        # by reports and the benchmark UI, then discard the staging directory.
        for name in ("events.jsonl", "gateway_responses.jsonl", "trajectory.json", "telemetry.json"):
            source = package_output / name
            if source.is_file():
                shutil.copy2(source, run_dir / name)
        shutil.rmtree(package_output, ignore_errors=True)
    metadata["finished_at"] = utc_now()
    metadata["duration_seconds"] = round(time.monotonic() - started, 3)
    metadata["container_cleaned"] = container_cleaned
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    if args.provider != "openhands" or not (run_dir / "telemetry.json").is_file():
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
