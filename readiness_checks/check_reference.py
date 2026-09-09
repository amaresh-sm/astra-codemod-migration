#!/usr/bin/env python3
"""Gate a task on reference evidence with a complete normalized score of 1.0."""

from __future__ import annotations

import argparse
import math
import tomllib
from pathlib import Path
from typing import Any

try:
    from .common import PASS_STATUSES, emit_result, load_json, status_value
except ImportError:  # Direct execution: ``python readiness_checks/check_reference.py``.
    from common import PASS_STATUSES, emit_result, load_json, status_value


def check_reference(proof_dir: Path) -> dict[str, Any]:
    """Validate every recorded reference run in ``proof_dir/reference-runs``."""

    runs_dir = proof_dir / "reference-runs"
    result: dict[str, Any] = {
        "check": "reference-score-gate",
        "proof_dir": str(proof_dir),
        "runs": [],
        "failures": [],
    }
    if not runs_dir.is_dir():
        result["failures"].append(f"missing reference-runs directory: {runs_dir}")
        result["ok"] = False
        return result

    runs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    if not runs:
        result["failures"].append("no reference runs have been recorded")

    # A copied proof directory can otherwise pass this gate while belonging to
    # an entirely different task.  The current scoring ledger is the stable
    # source of truth for the expected criterion set.
    scoring_path = proof_dir.parent / "scoring.yml"
    expected_criteria: set[str] = set()
    if scoring_path.is_file():
        for raw in scoring_path.read_text(encoding="utf-8").splitlines():
            stripped = raw.split("#", 1)[0].strip()
            if stripped.startswith("- id:"):
                criterion = stripped.partition(":")[2].strip().strip("'\"")
                if criterion:
                    expected_criteria.add(criterion)

    task_metadata_path = proof_dir.parent.parent / "tasks" / "task.toml"
    expected_task_id: str | None = None
    if task_metadata_path.is_file():
        try:
            value = tomllib.loads(task_metadata_path.read_text(encoding="utf-8")).get("id")
            if isinstance(value, str) and value:
                expected_task_id = value
        except (OSError, tomllib.TOMLDecodeError):
            pass

    for run_dir in runs:
        score_path = run_dir / "reports" / "score.json"
        run_result: dict[str, Any] = {"run": run_dir.name}
        result["runs"].append(run_result)
        if not score_path.is_file():
            result["failures"].append(f"{run_dir.name}: missing {score_path.relative_to(proof_dir)}")
            continue
        try:
            payload = load_json(score_path)
        except (OSError, ValueError, TypeError) as exc:
            result["failures"].append(f"{run_dir.name}: cannot read score evidence ({exc})")
            continue
        score = payload.get("score")
        hard_pass = payload.get("hard_pass")
        run_result.update({"score": score, "hard_pass": hard_pass})
        task_id = payload.get("task_id")
        if expected_task_id is not None and task_id != expected_task_id:
            result["failures"].append(
                f"{run_dir.name}: task_id is {task_id!r}, expected {expected_task_id!r}"
            )
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isclose(float(score), 1.0, abs_tol=1e-9)
        ):
            result["failures"].append(f"{run_dir.name}: score is {score!r}, expected 1.0")
        if hard_pass is not True:
            result["failures"].append(f"{run_dir.name}: hard_pass is not true")
        criteria = payload.get("criteria")
        if not isinstance(criteria, dict) or not criteria:
            result["failures"].append(f"{run_dir.name}: score report has no criteria ledger")
        else:
            if expected_criteria and set(criteria) != expected_criteria:
                missing = sorted(expected_criteria - set(criteria))
                extra = sorted(set(criteria) - expected_criteria)
                detail: list[str] = []
                if missing:
                    detail.append(f"missing: {', '.join(missing)}")
                if extra:
                    detail.append(f"unexpected: {', '.join(extra)}")
                result["failures"].append(
                    f"{run_dir.name}: criteria do not match current scoring ledger ({'; '.join(detail)})"
                )
            non_pass = sorted(
                key for key, value in criteria.items() if status_value(value) not in PASS_STATUSES
            )
            if non_pass:
                result["failures"].append(
                    f"{run_dir.name}: criteria are not all passing: {', '.join(non_pass)}"
                )
    result["ok"] = not result["failures"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--proof-dir",
        type=Path,
        default=Path("verifier/proof-of-work"),
        help="directory containing reference-runs/ (default: verifier/proof-of-work)",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args()
    result = check_reference(args.proof_dir.resolve())
    emit_result(result, args.json)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
