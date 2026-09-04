"""Calculate a normalized score from private verifier criterion results."""

from __future__ import annotations

import argparse
import json
import math
import tomllib
from pathlib import Path

SUPPORTED_BLOCKED_POLICIES = {"zero"}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score a verifier result")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--results", type=Path, default=None, help="Criterion result JSON; defaults to reports/criteria.json")
    return parser.parse_args()


def locate_verifier(task_dir: Path) -> Path:
    """Resolve the private verifier in either supported package layout."""
    nested = task_dir / "verifier"
    if nested.is_dir():
        return nested
    if task_dir.name == "tasks":
        flat_verifier = task_dir.parent / "verifier"
        if flat_verifier.is_dir():
            return flat_verifier
    repository_verifier = task_dir.parents[1] / "verifier" / task_dir.name
    if repository_verifier.is_dir():
        return repository_verifier
    raise SystemExit(f"private verifier is missing for task: {task_dir}")


def task_identifier(task_dir: Path) -> str:
    """Return the stable task id from task.toml for flat task packages."""
    try:
        metadata = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return task_dir.name
    value = metadata.get("id")
    return value if isinstance(value, str) and value else task_dir.name


def read_scoring(path: Path) -> list[dict[str, object]]:
    """Read the deliberately small scoring.yml format without a runtime dependency."""
    if not path.is_file():
        raise SystemExit(f"missing scoring.yml: {path}")
    criteria: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped or stripped in {"criteria:", "scale: normalized_1"}:
            continue
        if stripped.startswith("- "):
            if current is not None:
                criteria.append(current)
            current = {}
            stripped = stripped[2:].strip()
        if current is None:
            continue
        if ":" not in stripped:
            continue
        key, value = (part.strip() for part in stripped.split(":", 1))
        value = value.strip("'\"")
        if key == "weight":
            try:
                current[key] = float(value)
            except ValueError as exc:
                raise SystemExit(f"invalid weight for criterion: {value}") from exc
        else:
            current[key] = value
    if current is not None:
        criteria.append(current)
    if not criteria:
        raise SystemExit("scoring.yml must contain criteria")
    ids = [item.get("id") for item in criteria]
    if any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
        raise SystemExit("scoring.yml criteria need unique non-empty ids")
    if any(not isinstance(item.get("weight"), float) or item["weight"] <= 0 for item in criteria):
        raise SystemExit("scoring.yml weights must be positive numbers")
    unsupported = {
        str(item.get("blocked_policy"))
        for item in criteria
        if item.get("blocked_policy", "zero") not in SUPPORTED_BLOCKED_POLICIES
    }
    if unsupported:
        raise SystemExit(f"unsupported blocked_policy: {', '.join(sorted(unsupported))}")
    total = sum(item["weight"] for item in criteria)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise SystemExit(f"scoring.yml weights must sum to 1.0 (got {total:.12g})")
    return criteria


def read_results(path: Path) -> dict[str, tuple[str, float | None]]:
    if not path.is_file():
        raise SystemExit(f"missing verifier results: {path}")
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid verifier results JSON: {exc}") from exc
    raw = payload.get("criteria") if isinstance(payload, dict) else None
    result: dict[str, tuple[str, float | None]] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                status = str(value.get("status", "blocked"))
                numeric = value.get("score", value.get("value"))
                if numeric is not None and not isinstance(numeric, (int, float)):
                    raise SystemExit(f"criterion {key!r} has a non-numeric score")
                result[str(key)] = (status, float(numeric) if numeric is not None else None)
            else:
                result[str(key)] = (str(value), None)
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict) or "id" not in item:
                continue
            numeric = item.get("score", item.get("value"))
            if numeric is not None and not isinstance(numeric, (int, float)):
                raise SystemExit(f"criterion {item['id']!r} has a non-numeric score")
            result[str(item["id"])] = (str(item.get("status", "blocked")), float(numeric) if numeric is not None else None)
    else:
        raise SystemExit("verifier results must contain a criteria object or list")
    return result


def run(args: argparse.Namespace) -> int:
    task_dir = args.task.resolve()
    run_dir = args.run.resolve()
    criteria = read_scoring(locate_verifier(task_dir) / "scoring.yml")
    results_path = (args.results or (run_dir / "reports" / "criteria.json")).resolve()
    results = read_results(results_path)
    outcomes: dict[str, dict[str, object]] = {}
    score = 0.0
    hard_pass = True
    for criterion in criteria:
        criterion_id = str(criterion["id"])
        status, numeric = results.get(criterion_id, ("blocked", None))
        if numeric is not None and not 0.0 <= numeric <= 1.0:
            raise SystemExit(f"criterion {criterion_id!r} score must be between 0 and 1")
        awarded_fraction = numeric if numeric is not None else (1.0 if status == "pass" else 0.0)
        passed = status == "pass" and awarded_fraction == 1.0
        score += float(criterion["weight"]) * awarded_fraction
        if not passed:
            hard_pass = False
        outcomes[criterion_id] = {
            "status": status,
            "score": round(awarded_fraction, 10),
            "weight": criterion["weight"],
            "blocked_policy": criterion.get("blocked_policy", "zero"),
            "awarded": round(float(criterion["weight"]) * awarded_fraction, 10),
        }
    report = {
        "task_id": task_identifier(task_dir),
        "score": round(score, 10),
        "hard_pass": hard_pass,
        "criteria": outcomes,
    }
    reports = run_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "score.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if hard_pass else 1


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
