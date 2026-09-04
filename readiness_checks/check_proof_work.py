#!/usr/bin/env python3
"""Check that reference, mutant, and candidate proof-of-work evidence is usable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .common import emit_result, load_json
except ImportError:  # Direct execution: ``python readiness_checks/check_proof_work.py``.
    from common import emit_result, load_json


def _require_fields(value: dict[str, Any], fields: tuple[str, ...], context: str, failures: list[str]) -> None:
    """Require non-empty metadata fields and report all missing fields together."""

    missing = [field for field in fields if value.get(field) in (None, "")]
    if missing:
        failures.append(f"{context}: missing metadata: {', '.join(missing)}")


def _check_reference_runs(proof_dir: Path, failures: list[str]) -> list[dict[str, Any]]:
    runs = sorted(path for path in (proof_dir / "reference-runs").glob("*") if path.is_dir())
    if len(runs) < 2:
        failures.append(f"at least two reference runs are required (found {len(runs)})")
    rows: list[dict[str, Any]] = []
    for run in runs:
        context = f"reference/{run.name}"
        try:
            metadata = load_json(run / "verification.json")
            score = load_json(run / "reports/score.json")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            failures.append(f"{context}: unusable evidence ({exc})")
            continue
        _require_fields(
            metadata,
            ("task_id", "status", "started_at", "finished_at", "duration_seconds", "exit_code"),
            context,
            failures,
        )
        if metadata.get("status") != "passed" or metadata.get("exit_code") != 0:
            failures.append(f"{context}: verification did not finish successfully")
        if score.get("score") != 1.0 or score.get("hard_pass") is not True:
            failures.append(f"{context}: score evidence is not a complete hard pass")
        if not isinstance(score.get("criteria"), dict) or not score["criteria"]:
            failures.append(f"{context}: score criteria ledger is missing")
        rows.append({"run": run.name, "score": score.get("score"), "hard_pass": score.get("hard_pass")})
    return rows


def _check_mutant_runs(verifier_dir: Path, proof_dir: Path, failures: list[str]) -> list[dict[str, Any]]:
    """Check the evidence files for every patch listed in the mutation matrix."""

    try:
        matrix = load_json(proof_dir / "mutant-matrix.json").get("mutants")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        failures.append(f"mutant matrix is unusable ({exc})")
        return []
    if not isinstance(matrix, dict) or not matrix:
        failures.append("mutant matrix has no mutants")
        return []
    rows: list[dict[str, Any]] = []
    for name in sorted(matrix):
        context = f"mutant/{name}"
        run = proof_dir / "mutant-runs" / name
        patch = verifier_dir / "mutants" / f"{name}.patch"
        required = [
            run / "mutant.patch",
            run / "verification.json",
            run / "reports/score.json",
            run / "reports/backend/reward.json",
        ]
        missing = [str(path.relative_to(proof_dir)) for path in required if not path.is_file()]
        if not patch.is_file():
            missing.append(str(patch.relative_to(verifier_dir)))
        if missing:
            failures.append(f"{context}: missing evidence: {', '.join(missing)}")
            continue
        try:
            metadata = load_json(run / "verification.json")
            score = load_json(run / "reports/score.json")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            failures.append(f"{context}: unusable evidence ({exc})")
            continue
        _require_fields(
            metadata,
            ("task_id", "status", "started_at", "finished_at", "duration_seconds", "exit_code"),
            context,
            failures,
        )
        if metadata.get("status") != "passed" or metadata.get("exit_code") != 0:
            failures.append(f"{context}: verification did not finish successfully")
        if not isinstance(score.get("score"), (int, float)) or score.get("score") >= 1.0:
            failures.append(f"{context}: mutant score is not below 1.0")
        if score.get("hard_pass") is not False:
            failures.append(f"{context}: hard_pass must be false")
        rows.append({"mutant": name, "score": score.get("score"), "hard_pass": score.get("hard_pass")})
    return rows


def _check_candidate_runs(proof_dir: Path, failures: list[str]) -> list[dict[str, Any]]:
    runs = sorted(path for path in (proof_dir / "candidate-runs").glob("*") if path.is_dir())
    if len(runs) < 2:
        failures.append(f"at least two frontier-model candidate runs are required (found {len(runs)})")
    rows: list[dict[str, Any]] = []
    for run in runs:
        context = f"candidate/{run.name}"
        metadata_path = run / "metadata.json"
        if not metadata_path.is_file():
            # Historical exports use provenance.json; it is accepted as the run metadata file.
            metadata_path = run / "provenance.json"
        try:
            metadata = load_json(metadata_path)
            verification = load_json(run / "verification.json")
            score = load_json(run / "score.json")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            failures.append(f"{context}: unusable evidence ({exc})")
            continue
        _require_fields(
            metadata,
            ("source_run_id", "provider", "model", "reasoning", "generation_elapsed_seconds", "source_exit_code"),
            context,
            failures,
        )
        if metadata.get("source_exit_code") != 0:
            failures.append(f"{context}: generation did not finish successfully")
        if metadata.get("source_tamper_check") != "clean":
            failures.append(f"{context}: source tamper check is not clean")
        if verification.get("status") != "passed" or verification.get("exit_code") != 0:
            failures.append(f"{context}: verifier did not finish successfully")
        if not isinstance(score.get("score"), (int, float)) or not isinstance(score.get("hard_pass"), bool):
            failures.append(f"{context}: normalized score or hard_pass metadata is missing")
        rows.append({
            "run": run.name,
            "provider": metadata.get("provider"),
            "model": metadata.get("model"),
            "reasoning": metadata.get("reasoning"),
            "score": score.get("score"),
            "hard_pass": score.get("hard_pass"),
        })
    return rows


def check_proof_work(verifier_dir: Path, proof_dir: Path) -> dict[str, Any]:
    """Validate stored proof-of-work metadata for the current task."""

    verifier_dir = verifier_dir.resolve()
    proof_dir = proof_dir.resolve()
    failures: list[str] = []
    result: dict[str, Any] = {
        "check": "proof-of-work-evidence",
        "verifier_dir": str(verifier_dir),
        "proof_dir": str(proof_dir),
        "reference_runs": _check_reference_runs(proof_dir, failures),
        "mutant_runs": _check_mutant_runs(verifier_dir, proof_dir, failures),
        "candidate_runs": _check_candidate_runs(proof_dir, failures),
        "failures": failures,
    }
    result["ok"] = not failures
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verifier-dir", type=Path, default=Path("verifier"))
    parser.add_argument("--proof-dir", type=Path, default=Path("verifier/proof-of-work"))
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args()
    result = check_proof_work(args.verifier_dir, args.proof_dir)
    emit_result(result, args.json)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
