#!/usr/bin/env python3
"""Check mutant application, mapped detection, and absence of unrelated regressions."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

try:
    from .common import PASS_STATUSES, emit_result, load_json, status_value
except ImportError:  # Direct execution: ``python readiness_checks/check_mutants.py``.
    from common import PASS_STATUSES, emit_result, load_json, status_value


def _criterion_statuses(payload: dict[str, Any]) -> dict[str, str]:
    values = payload.get("criterionStatus")
    if not isinstance(values, dict):
        return {}
    return {str(key): status_value(value) for key, value in values.items()}


def _run_mutant(
    proof_dir: Path,
    name: str,
    patch_source: Path,
    mapping: dict[str, Any],
    baseline: dict[str, str],
) -> dict[str, Any]:
    """Evaluate one mutant against the reference criterion-status baseline."""

    run_dir = proof_dir / "mutant-runs" / name
    expected = {str(value) for value in mapping.get("expected_criteria", [])}
    related = {str(value) for value in mapping.get("related_criteria", [])}
    hidden_test = mapping.get("hidden_test")
    result: dict[str, Any] = {
        "mutant": name,
        "expected_criteria": sorted(expected),
        "related_criteria": sorted(related),
        "hidden_test": hidden_test,
        "failures": [],
    }
    if not expected:
        result["failures"].append("mapping has no expected criteria")
    if not isinstance(hidden_test, str) or not hidden_test.strip():
        result["failures"].append("mapping has no hidden_test")
    patch_path = run_dir / "mutant.patch"
    score_path = run_dir / "reports" / "score.json"
    reward_path = run_dir / "reports" / "backend" / "reward.json"
    verification_path = run_dir / "verification.json"
    if not run_dir.is_dir():
        result["failures"].append("proof run is missing")
    if not patch_path.is_file() or not patch_path.read_text(encoding="utf-8").strip():
        result["failures"].append("mutant.patch is missing or empty")
    elif patch_source.is_file():
        source_hash = hashlib.sha256(patch_source.read_bytes()).hexdigest()
        run_hash = hashlib.sha256(patch_path.read_bytes()).hexdigest()
        result["patch_sha256"] = run_hash
        if source_hash != run_hash:
            result["failures"].append("proof patch differs from verifier/mutants patch")
    if not score_path.is_file():
        result["failures"].append("reports/score.json is missing")
    if not reward_path.is_file():
        result["failures"].append("reports/backend/reward.json is missing")
    if not verification_path.is_file():
        result["failures"].append("verification.json is missing")
    if result["failures"]:
        result["ok"] = False
        return result
    try:
        verification = load_json(verification_path)
        score = load_json(score_path)
        reward = load_json(reward_path)
    except (OSError, ValueError, TypeError) as exc:
        result["failures"].append(f"malformed evidence: {exc}")
        result["ok"] = False
        return result
    if verification.get("status") not in ("passed", "complete"):
        result["failures"].append(f"verification status is {verification.get('status')!r}")
    if (
        isinstance(score.get("score"), bool)
        or not isinstance(score.get("score"), (int, float))
        or float(score["score"]) >= 1.0
    ):
        result["failures"].append(f"mutant score is not below 1.0: {score.get('score')!r}")
    if score.get("hard_pass") is not False:
        result["failures"].append(f"hard_pass is not false: {score.get('hard_pass')!r}")

    current = _criterion_statuses(reward)
    if not current:
        result["failures"].append("backend reward has no criterionStatus ledger")
        result["ok"] = False
        return result
    changed = {
        criterion
        for criterion, baseline_status in baseline.items()
        if baseline_status in PASS_STATUSES and current.get(criterion) not in PASS_STATUSES
    }
    result["changed_from_reference"] = sorted(changed)
    result["caught_criteria"] = sorted(changed & expected)
    if isinstance(hidden_test, str):
        criterion_ledger = reward.get("criterionStatus") or {}
        wrong_test = sorted(
            criterion
            for criterion in expected
            if isinstance(criterion_ledger.get(criterion), dict)
            and criterion_ledger[criterion].get("scenarioId") != hidden_test
        )
        if wrong_test:
            result["failures"].append(
                f"mapped criteria were not reported by {hidden_test}: {', '.join(wrong_test)}"
            )
    missing_expected = sorted(expected - changed)
    unrelated = sorted(changed - expected - related)
    if missing_expected:
        result["failures"].append(
            f"mapped criteria did not regress: {', '.join(missing_expected)}"
        )
    if unrelated:
        result["failures"].append(
            f"unrelated criteria regressed: {', '.join(unrelated)}"
        )
    result["ok"] = not result["failures"]
    return result


def check_mutants(verifier_dir: Path, proof_dir: Path) -> dict[str, Any]:
    """Evaluate every patch in ``verifier_dir/mutants`` against reference evidence."""

    result: dict[str, Any] = {
        "check": "mutant-coverage",
        "verifier_dir": str(verifier_dir),
        "proof_dir": str(proof_dir),
        "mutants": [],
        "failures": [],
    }
    mutants_dir = verifier_dir / "mutants"
    matrix_path = proof_dir / "mutant-matrix.json"
    if not mutants_dir.is_dir():
        result["failures"].append(f"missing mutants directory: {mutants_dir}")
    if not matrix_path.is_file():
        result["failures"].append(f"missing mutant mapping: {matrix_path}")
    if result["failures"]:
        result["ok"] = False
        return result
    try:
        matrix = load_json(matrix_path).get("mutants")
    except (OSError, ValueError, TypeError) as exc:
        result["failures"].append(f"cannot read mutant mapping: {exc}")
        result["ok"] = False
        return result
    if not isinstance(matrix, dict):
        result["failures"].append("mutant mapping must contain a mutants object")
        result["ok"] = False
        return result

    reference_runs = sorted(
        path for path in (proof_dir / "reference-runs").glob("*") if path.is_dir()
    )
    if not reference_runs:
        result["failures"].append("no reference run is available for comparison")
        result["ok"] = False
        return result
    baseline_path = reference_runs[0] / "reports" / "backend" / "reward.json"
    if not baseline_path.is_file():
        result["failures"].append(f"reference criterion ledger is missing: {baseline_path}")
        result["ok"] = False
        return result
    try:
        baseline = _criterion_statuses(load_json(baseline_path))
    except (OSError, ValueError, TypeError) as exc:
        result["failures"].append(f"cannot read reference criterion ledger: {exc}")
        result["ok"] = False
        return result
    if not baseline:
        result["failures"].append("reference reward has no criterionStatus ledger")
        result["ok"] = False
        return result

    patch_names = {path.stem for path in mutants_dir.glob("*.patch")}
    mapped_names = {str(name) for name in matrix}
    for name in sorted(patch_names | mapped_names):
        mapping = matrix.get(name)
        if not isinstance(mapping, dict):
            result["mutants"].append({"mutant": name, "failures": ["no mapping entry"]})
            continue
        if name not in patch_names:
            result["mutants"].append({"mutant": name, "failures": ["mapping has no patch file"]})
            continue
        result["mutants"].append(
            _run_mutant(proof_dir, name, mutants_dir / f"{name}.patch", mapping, baseline)
        )
    result["failures"].extend(
        f"{row['mutant']}: {failure}"
        for row in result["mutants"]
        for failure in row.get("failures", [])
    )
    result["ok"] = not result["failures"] and bool(patch_names)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verifier-dir",
        type=Path,
        default=Path("verifier"),
        help="task verifier directory (default: verifier)",
    )
    parser.add_argument(
        "--proof-dir",
        type=Path,
        default=Path("verifier/proof-of-work"),
        help="directory containing mutant-runs/ and mutant-matrix.json",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args()
    result = check_mutants(args.verifier_dir.resolve(), args.proof_dir.resolve())
    emit_result(result, args.json)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
