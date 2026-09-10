"""Create local proof evidence for the migration verifier.

This authoring utility runs the same Docker benchmark command used for submitted
candidates, then stores criterion/status ledgers for repeatability and mutation
coverage. It is intentionally not candidate-visible.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROOF = Path(__file__).resolve().parent
REF = ROOT / "verifier/reference-solution"
PATCHES = ROOT / "verifier/mutants"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_once(candidate: Path, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    # A previously interrupted local calibration can leave one disposable
    # runtime behind. Remove only the deterministic container for this proof
    # slot before reusing it.
    runtime_name = f"astra-verify-migrate-jscodeshift-runner-to-rust-{destination.name}-runtime"
    subprocess.run(
        ["docker", "rm", "--force", runtime_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.monotonic()
    result = subprocess.run(
        [
            "npm", "run", "benchmark", "--",
            "--task", str(ROOT / "tasks"),
            "--candidate", str(candidate),
            "--run", str(destination),
            "--timeout-seconds", "1800",
        ],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    finished = time.monotonic()
    metadata = {
        "task_id": "migrate-jscodeshift-runner-to-rust",
        "status": "passed" if result.returncode == 0 else "failed",
        "started_at": stamp(), "finished_at": stamp(),
        "duration_seconds": round(finished - started, 3),
        "exit_code": result.returncode,
        "verifier_exit_code": result.returncode,
    }
    (destination / "verification.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"{destination.name}: {'pass' if result.returncode == 0 else 'FAIL'} ({metadata['duration_seconds']}s)")
    return result.returncode


def main() -> None:
    for directory in (PROOF / "reference-runs", PROOF / "mutant-runs"):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
    for index in range(1, 6):
        run_once(REF, PROOF / "reference-runs" / f"reference-{index}")
    for patch in sorted(PATCHES.glob("*.patch")):
        name = patch.stem
        with tempfile.TemporaryDirectory(prefix="codemod-proof-") as directory:
            candidate = Path(directory) / "candidate"
            shutil.copytree(REF, candidate)
            subprocess.run(["patch", "-p1", "-s", "-i", str(patch)], cwd=candidate, check=True)
            destination = PROOF / "mutant-runs" / name
            run_once(candidate, destination)
            shutil.copy2(patch, destination / "mutant.patch")
    print(f"recorded five reference runs and {len(list(PATCHES.glob('*.patch')))} mutant runs")


if __name__ == "__main__":
    main()
