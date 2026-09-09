"""Prepare benchmark images, verify one candidate, and publish its score."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERIFIER_COMMAND = "python3 /input/verifier/run.py --candidate /input/candidate --output /output"

IMAGE_SOURCES = {
    "runtime": (
        REPOSITORY_ROOT / "environment/candidate-runtime/Dockerfile",
        REPOSITORY_ROOT / "environment/candidate-runtime/entrypoint.sh",
    ),
    "verifier": (
        REPOSITORY_ROOT / "environment/verifier/Dockerfile",
        REPOSITORY_ROOT / "environment/verifier/entrypoint.sh",
    ),
}


def source_digest(paths: tuple[Path, ...]) -> str:
    """Return a stable digest for the files that define one image."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(REPOSITORY_ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def image_is_current(tag: str, expected_digest: str) -> bool:
    """Check both image existence and its recorded source digest."""
    result = subprocess.run(
        [
            "docker", "image", "inspect", tag,
            "--format", "{{index .Config.Labels \"astra.source-digest\"}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == expected_digest


def ensure_image(tag: str, dockerfile: Path, sources: tuple[Path, ...]) -> None:
    """Build an image only when it is missing or its source files changed."""
    expected_digest = source_digest(sources)
    if image_is_current(tag, expected_digest):
        print(f"[images] ready: {tag}")
        return
    print(f"[images] building: {tag}")
    subprocess.run(
        [
            "docker", "build",
            "--label", f"astra.source-digest={expected_digest}",
            "--tag", tag,
            "--file", str(dockerfile),
            ".",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare, verify, and score one candidate")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--verifier-command", default=DEFAULT_VERIFIER_COMMAND)
    parser.add_argument("--image", default="astra-verifier:latest")
    parser.add_argument("--runtime-image", default="astra-candidate-runtime:latest")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=14_400)
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    """Run image preparation, isolated verification, and scoring as one operation."""
    run_dir = args.run.resolve()
    criteria_path = run_dir / "reports" / "criteria.json"
    if criteria_path.exists():
        raise SystemExit(f"refusing to reuse an existing verifier report: {criteria_path}")

    ensure_image(
        args.runtime_image,
        REPOSITORY_ROOT / "environment/candidate-runtime/Dockerfile",
        IMAGE_SOURCES["runtime"],
    )
    ensure_image(
        args.image,
        REPOSITORY_ROOT / "environment/verifier/Dockerfile",
        IMAGE_SOURCES["verifier"],
    )

    verify_command = [
        sys.executable, "-m", "astra_harness.verify",
        "--task", str(args.task),
        "--candidate", str(args.candidate),
        "--run", str(run_dir),
        "--verifier-command", args.verifier_command,
        "--image", args.image,
        "--runtime-image", args.runtime_image,
        "--timeout-seconds", str(args.timeout_seconds),
    ]
    if args.env_file:
        verify_command.extend(("--env-file", str(args.env_file)))

    print("[verify] running isolated candidate verification")
    verify_result = subprocess.run(verify_command, cwd=REPOSITORY_ROOT, check=False)
    metadata_path = run_dir / "verification.json"
    if verify_result.returncode != 0 or not metadata_path.is_file():
        raise SystemExit(f"verification did not complete successfully: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "passed":
        raise SystemExit(f"verification failed; inspect {metadata_path}")

    print("[score] calculating normalized score")
    score_result = subprocess.run(
        [
            sys.executable, "-m", "astra_harness.score",
            "--task", str(args.task),
            "--run", str(run_dir),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    score_path = run_dir / "reports" / "score.json"
    if not score_path.is_file():
        raise SystemExit(f"scoring did not produce a report: {score_path}")
    score = json.loads(score_path.read_text(encoding="utf-8"))
    print(f"[done] score={score['score']:.4f} report={score_path}")
    # A low-scoring candidate is a valid benchmark result, not an orchestration error.
    return 0 if score_result.returncode in (0, 1) else score_result.returncode


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
