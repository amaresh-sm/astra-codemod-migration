#!/usr/bin/env python3
"""Validate scoring configuration and the zero-value policy for blocked results."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

try:
    from astra_harness.score import read_scoring
    from .common import load_json, emit_result, status_value
except ImportError:  # Direct execution from a checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from astra_harness.score import read_scoring
    from common import load_json, emit_result, status_value


def _blocked_violations(proof_dir: Path) -> list[str]:
    """Find score reports that award anything to a blocked criterion."""

    violations: list[str] = []
    for report_path in sorted(proof_dir.rglob("reports/score.json")):
        try:
            report = load_json(report_path)
        except (OSError, ValueError, TypeError) as exc:
            violations.append(f"{report_path}: malformed score report ({exc})")
            continue
        criteria = report.get("criteria")
        if not isinstance(criteria, dict):
            violations.append(f"{report_path}: score report has no criteria object")
            continue
        for criterion_id, value in criteria.items():
            if status_value(value) != "blocked":
                continue
            if not isinstance(value, dict):
                violations.append(f"{report_path}: blocked criterion {criterion_id!r} has no score object")
                continue
            if value.get("score") != 0 or value.get("awarded") != 0:
                violations.append(
                    f"{report_path}: blocked criterion {criterion_id!r} has "
                    f"score={value.get('score')!r}, awarded={value.get('awarded')!r}"
                )
    return violations


def check_scoring(verifier_dir: Path, proof_dir: Path) -> dict[str, Any]:
    """Validate the scoring schema and every recorded blocked-result award."""

    verifier_dir = verifier_dir.resolve()
    proof_dir = proof_dir.resolve()
    scoring_path = verifier_dir / "scoring.yml"
    result: dict[str, Any] = {
        "check": "scoring-validity",
        "scoring_file": str(scoring_path),
        "proof_dir": str(proof_dir),
        "failures": [],
    }
    try:
        criteria = read_scoring(scoring_path)
    except SystemExit as exc:
        result["failures"].append(str(exc))
        result["ok"] = False
        return result
    ids = [str(item["id"]) for item in criteria]
    weights = [float(item["weight"]) for item in criteria]
    total = sum(weights)
    result.update({"criterion_ids": ids, "criterion_count": len(ids), "weight_total": total})
    if len(ids) != len(set(ids)):
        result["failures"].append("criterion IDs are not unique")
    if any(weight <= 0 for weight in weights):
        result["failures"].append("criterion weights must be positive")
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        result["failures"].append(f"criterion weights total {total:.12g}, expected 1.0")
    result["blocked_result_violations"] = _blocked_violations(proof_dir)
    result["failures"].extend(result["blocked_result_violations"])
    result["ok"] = not result["failures"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verifier-dir", type=Path, default=Path("verifier"))
    parser.add_argument("--proof-dir", type=Path, default=Path("verifier/proof-of-work"))
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args()
    result = check_scoring(args.verifier_dir, args.proof_dir)
    emit_result(result, args.json)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
