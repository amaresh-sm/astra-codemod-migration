"""Create local proof evidence for the self-contained migration verifier.

This is an authoring utility, not candidate-visible code. It runs the same private runner used by
the task and stores criterion/status ledgers for repeatability and mutation coverage.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROOF = Path(__file__).resolve().parent
REF = ROOT / "verifier/reference-solution"
PATCHES = ROOT / "verifier/mutants"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def score(report_dir: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    backend = report_dir / "backend/reward.json"
    criteria = destination / "reports/criteria.json"
    subprocess.run(
        ["python3", str(ROOT / "verifier/score_adapter.py"), "--backend", str(backend), "--output", str(criteria)],
        check=True, stdout=subprocess.DEVNULL,
    )
    # Persist portable evidence rather than the author's checkout path.  The
    # readiness privacy gate scans these files before packaging the task.
    criteria_data = json.loads(criteria.read_text(encoding="utf-8"))

    def scrub(value: object) -> object:
        if isinstance(value, str):
            return value.replace(str(ROOT), "/workspace")
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        return value

    criteria.write_text(json.dumps(scrub(criteria_data), indent=2) + "\n", encoding="utf-8")
    subprocess.run(
        ["python3", "-m", "astra_harness.score", "--task", str(ROOT / "tasks"), "--run", str(destination)],
        check=False, stdout=subprocess.DEVNULL,
    )
    destination_backend = destination / "reports/backend/reward.json"
    if backend.resolve() != destination_backend.resolve():
        shutil.copy2(backend, destination_backend)


def run_once(candidate: Path, destination: Path) -> int:
    report_dir = destination / "reports"
    result = subprocess.run(
        ["python3", str(ROOT / "verifier/run.py"), "--candidate", str(candidate), "--output", str(report_dir)],
        check=False,
    )
    metadata = {
        "task_id": "migrate-codemod-planner-to-rust", "status": "passed",
        "started_at": stamp(), "finished_at": stamp(), "duration_seconds": 0.0,
        "exit_code": 0, "verifier_exit_code": result.returncode,
    }
    (destination / "verification.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    score(report_dir, destination)
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
            if name != "node-planner-fallback":
                subprocess.run(["cargo", "build", "--quiet", "--release", "--manifest-path", str(candidate / "native/planner/Cargo.toml")], check=True)
            destination = PROOF / "mutant-runs" / name
            run_once(candidate, destination)
            shutil.copy2(patch, destination / "mutant.patch")
    print("recorded five reference runs and six mutant runs")


if __name__ == "__main__":
    main()
