#!/usr/bin/env python3
"""Check that repeated reference runs produce identical observable outcomes."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from .common import emit_result, load_json, status_value
except ImportError:  # Direct execution: ``python readiness_checks/check_determinism.py``.
    from common import emit_result, load_json, status_value


def _outcomes(run_dir: Path) -> dict[str, dict[str, str]]:
    """Read stable status ledgers, excluding dynamic IDs and evidence values."""

    outcomes: dict[str, dict[str, str]] = {}
    backend = run_dir / "reports/backend/reward.json"
    ui = run_dir / "reports/ui/ui-reward.json"
    score = run_dir / "reports/score.json"
    if backend.is_file():
        payload = load_json(backend)
        ledger = payload.get("criterionStatus")
        if isinstance(ledger, dict):
            outcomes["backend"] = {
                str(key): status_value(value) for key, value in sorted(ledger.items())
            }
    if ui.is_file():
        payload = load_json(ui)
        capabilities = payload.get("capabilities")
        if isinstance(capabilities, list):
            outcomes["ui"] = {
                str(item["id"]): status_value(item)
                for item in capabilities
                if isinstance(item, dict) and item.get("id")
            }
    if score.is_file():
        payload = load_json(score)
        ledger = payload.get("criteria")
        if isinstance(ledger, dict):
            outcomes["score"] = {
                str(key): status_value(value) for key, value in sorted(ledger.items())
            }
    return outcomes


def check_determinism(proof_dir: Path) -> dict[str, Any]:
    """Require at least two reference runs with equal status ledgers and scores."""

    runs_dir = proof_dir.resolve() / "reference-runs"
    run_dirs = sorted(path for path in runs_dir.glob("*") if path.is_dir())
    result: dict[str, Any] = {
        "check": "reference-determinism",
        "proof_dir": str(proof_dir.resolve()),
        "runs": [],
        "failures": [],
    }
    if len(run_dirs) < 2:
        result["failures"].append(
            f"at least two reference runs are required (found {len(run_dirs)})"
        )
        result["ok"] = False
        return result
    snapshots: list[tuple[str, dict[str, Any]]] = []
    for run_dir in run_dirs:
        score_path = run_dir / "reports/score.json"
        try:
            score = load_json(score_path)
            outcomes = _outcomes(run_dir)
        except (OSError, ValueError, TypeError) as exc:
            result["failures"].append(f"{run_dir.name}: malformed evidence ({exc})")
            continue
        if not outcomes.get("backend"):
            result["failures"].append(f"{run_dir.name}: backend criterion ledger is missing")
        if not outcomes.get("score"):
            result["failures"].append(f"{run_dir.name}: score criterion ledger is missing")
        snapshot = {
            "outcomes": outcomes,
            "score": score.get("score"),
            "hard_pass": score.get("hard_pass"),
        }
        snapshots.append((run_dir.name, snapshot))
        result["runs"].append({
            "run": run_dir.name,
            "score": score.get("score"),
            "hard_pass": score.get("hard_pass"),
            "ledgers": sorted(outcomes),
        })
    if snapshots:
        baseline_name, baseline = snapshots[0]
        for name, current in snapshots[1:]:
            if current != baseline:
                result["failures"].append(
                    f"{name}: criterion outcomes or score differ from {baseline_name}"
                )
    result["ok"] = not result["failures"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-dir", type=Path, default=Path("verifier/proof-of-work"))
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args()
    result = check_determinism(args.proof_dir)
    emit_result(result, args.json)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
