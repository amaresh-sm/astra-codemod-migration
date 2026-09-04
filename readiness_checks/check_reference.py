#!/usr/bin/env python3
"""Gate a task on reference evidence with a complete normalized score of 1.0."""

from __future__ import annotations

import argparse
import math
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
