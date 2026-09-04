#!/usr/bin/env python3
"""Check that acceptance criteria are complete and agree with scoring.yml."""

from __future__ import annotations

import argparse
import math
import sys
import tomllib
from pathlib import Path
from typing import Any

try:
    from astra_harness.acceptance import read_acceptance
    from astra_harness.score import read_scoring
    from .common import emit_result
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from astra_harness.acceptance import read_acceptance
    from astra_harness.score import read_scoring
    from common import emit_result


REQUIRED_FIELDS = ("id", "requirement", "hidden_test", "mutant", "weight")


def task_id(task_dir: Path) -> str:
    """Read the task's stable ID without relying on its directory name."""

    try:
        data = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"cannot read task.toml: {exc}") from exc
    value = data.get("id")
    if not isinstance(value, str) or not value:
        raise SystemExit("task.toml has no valid id")
    return value


def check_acceptance(task_dir: Path, verifier_dir: Path) -> dict[str, Any]:
    """Validate acceptance completeness and exact scoring alignment."""

    result: dict[str, Any] = {"check": "acceptance-and-scoring-alignment", "failures": []}
    try:
        expected_task_id = task_id(task_dir)
        acceptance_task_id, criteria = read_acceptance(verifier_dir / "acceptance-criteria.yml")
        scoring = read_scoring(verifier_dir / "scoring.yml")
    except SystemExit as exc:
        result["failures"].append(str(exc))
        result["ok"] = False
        return result

    result.update({"task_id": expected_task_id, "criterion_count": len(criteria)})
    if acceptance_task_id != expected_task_id:
        result["failures"].append(
            f"acceptance task_id {acceptance_task_id!r} does not match task.toml id {expected_task_id!r}"
        )

    acceptance_by_id: dict[str, dict[str, object]] = {}
    for index, criterion in enumerate(criteria, start=1):
        missing = [field for field in REQUIRED_FIELDS if field not in criterion]
        if missing:
            result["failures"].append(f"criterion #{index} is missing: {', '.join(missing)}")
            continue
        criterion_id = criterion.get("id")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            result["failures"].append(f"criterion #{index} has no valid id")
            continue
        if criterion_id in acceptance_by_id:
            result["failures"].append(f"duplicate acceptance criterion id: {criterion_id}")
            continue
        for field in ("requirement", "hidden_test", "mutant"):
            if not isinstance(criterion.get(field), str) or not str(criterion[field]).strip():
                result["failures"].append(f"criterion {criterion_id!r} has no valid {field}")
        weight = criterion.get("weight")
        if not isinstance(weight, float) or weight <= 0:
            result["failures"].append(f"criterion {criterion_id!r} has no positive weight")
        acceptance_by_id[criterion_id] = criterion

    scoring_by_id = {str(item["id"]): item for item in scoring}
    acceptance_ids = set(acceptance_by_id)
    scoring_ids = set(scoring_by_id)
    if acceptance_ids != scoring_ids:
        missing_from_scoring = sorted(acceptance_ids - scoring_ids)
        missing_from_acceptance = sorted(scoring_ids - acceptance_ids)
        if missing_from_scoring:
            result["failures"].append("acceptance criteria absent from scoring.yml: " + ", ".join(missing_from_scoring))
        if missing_from_acceptance:
            result["failures"].append("scoring criteria absent from acceptance-criteria.yml: " + ", ".join(missing_from_acceptance))
    for criterion_id in sorted(acceptance_ids & scoring_ids):
        acceptance_weight = acceptance_by_id[criterion_id].get("weight")
        scoring_weight = scoring_by_id[criterion_id].get("weight")
        if not isinstance(acceptance_weight, float) or not isinstance(scoring_weight, float):
            continue
        if not math.isclose(acceptance_weight, scoring_weight, rel_tol=0.0, abs_tol=1e-9):
            result["failures"].append(
                f"weight differs for {criterion_id}: acceptance={acceptance_weight}, scoring={scoring_weight}"
            )
    result["ok"] = not result["failures"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, default=Path("tasks"))
    parser.add_argument("--verifier-dir", type=Path, default=Path("verifier"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_acceptance(args.task_dir.resolve(), args.verifier_dir.resolve())
    emit_result(result, args.json)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
