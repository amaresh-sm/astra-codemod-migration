"""Calculate a normalized score from private verifier criterion results."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tomllib
from pathlib import Path

SUPPORTED_BLOCKED_POLICIES = {"zero"}
FOUNDATION_DOMAIN = "foundation"
THIN_WRAPPER_CAP = 0.04


class ScoringConfig(list[dict[str, object]]):
    """List-compatible scoring criteria with optional score components."""


def _criterion_fraction(
    criterion: dict[str, object], results: dict[str, tuple[str, float | None]]
) -> tuple[str, float]:
    """Resolve one criterion's normalized result without assigning score credit."""

    criterion_id = str(criterion["id"])
    status, numeric = results.get(criterion_id, ("blocked", None))
    if numeric is not None and not 0.0 <= numeric <= 1.0:
        raise SystemExit(f"criterion {criterion_id!r} score must be between 0 and 1")
    return status, numeric if numeric is not None else (1.0 if status == "pass" else 0.0)

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


def verifier_revision(verifier_dir: Path) -> str:
    """Hash the executable verifier and ledger, excluding mutable proof data."""

    digest = hashlib.sha256()
    excluded = {"proof-of-work", "__pycache__"}
    for path in sorted(verifier_dir.rglob("*")):
        if not path.is_file() or excluded.intersection(path.relative_to(verifier_dir).parts):
            continue
        relative = path.relative_to(verifier_dir).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def task_identifier(task_dir: Path) -> str:
    """Return the stable task id from task.toml for flat task packages."""
    try:
        metadata = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return task_dir.name
    value = metadata.get("id")
    return value if isinstance(value, str) and value else task_dir.name


def read_scoring(path: Path) -> ScoringConfig:
    """Read the deliberately small scoring.yml format without a runtime dependency."""
    if not path.is_file():
        raise SystemExit(f"missing scoring.yml: {path}")
    criteria: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    section: str | None = None
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped or stripped in {"criteria:", "scale: normalized_1"}:
            if stripped == "criteria:":
                section = "criteria"
            continue
        if section != "criteria":
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
    components = {str(item.get("component", "")) for item in criteria}
    required_components = {"operational", "behavior", "migration_foundation", "rust_ownership"}
    if not required_components.issubset(components):
        missing = ", ".join(sorted(required_components - components))
        raise SystemExit(f"scoring.yml is missing ownership-gated components: {missing}")
    for item in criteria:
        component = str(item.get("component", ""))
        domain = item.get("domain")
        if component in {"behavior", "rust_ownership"} and not isinstance(domain, str):
            raise SystemExit(f"criterion {item['id']!r} needs a migration domain")
        if component == "migration_foundation" and domain != FOUNDATION_DOMAIN:
            raise SystemExit("migration foundation must use domain: foundation")
    return ScoringConfig(criteria)


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
    verifier_dir = locate_verifier(task_dir)
    scoring = read_scoring(verifier_dir / "scoring.yml")
    criteria = scoring
    results_path = (args.results or (run_dir / "reports" / "criteria.json")).resolve()
    results = read_results(results_path)
    outcomes: dict[str, dict[str, object]] = {}
    component_totals: dict[str, float] = {}
    component_scores: dict[str, float] = {}
    raw_component_scores: dict[str, float] = {}
    domain_totals: dict[str, float] = {}
    domain_scores: dict[str, float] = {}
    hard_pass = True

    # First collect independent evidence.  It is deliberately not scored yet:
    # a JavaScript engine can satisfy public behavior while proving no Rust
    # migration at all.
    for criterion in criteria:
        criterion_id = str(criterion["id"])
        status, awarded_fraction = _criterion_fraction(criterion, results)
        passed = status == "pass" and awarded_fraction == 1.0
        weight = float(criterion["weight"])
        component = str(criterion.get("component", "unclassified"))
        component_totals[component] = component_totals.get(component, 0.0) + weight
        raw_component_scores[component] = raw_component_scores.get(component, 0.0) + weight * awarded_fraction
        domain = str(criterion.get("domain", ""))
        if component == "rust_ownership":
            domain_totals[domain] = domain_totals.get(domain, 0.0) + weight
            domain_scores[domain] = domain_scores.get(domain, 0.0) + weight * awarded_fraction
        if not passed:
            hard_pass = False
        outcomes[criterion_id] = {
            "status": status,
            "score": round(awarded_fraction, 10),
            "weight": weight,
            "blocked_policy": criterion.get("blocked_policy", "zero"),
            "raw_awarded": round(weight * awarded_fraction, 10),
        }

    foundation = next(item for item in criteria if item.get("component") == "migration_foundation")
    foundation_id = str(foundation["id"])
    # The migration criterion is fractional: its first 0.05 establishes a
    # native Rust foundation and its remaining allowance records independently
    # evidenced migration progress. A partial result can therefore establish
    # a valid foundation without claiming every progress subsystem.
    foundation_passed = float(outcomes[foundation_id]["raw_awarded"]) >= 0.05
    owned_domain_score = sum(domain_scores.values())
    # Ownership probes are intentionally independent. A retained JavaScript
    # AST bridge blocks AST/core/package probes, but must not erase separately
    # traced native CLI, file, or worker evidence.
    native_domain_migration = foundation_passed and owned_domain_score > 0.0
    native_foundation_only = foundation_passed and owned_domain_score == 0.0

    # A thin wrapper may have excellent compatibility evidence, but that
    # evidence came from retained JavaScript and must never rank as a Rust
    # migration.  Keep a small, graduated operational score so diagnostics
    # still distinguish a working launcher from a completely broken artifact.
    observed_wrapper_score = sum(
        raw_component_scores.get(component, 0.0) for component in ("operational", "behavior")
    )
    if native_foundation_only:
        # The executable Rust migration is real, but the verifier cannot
        # attribute individual compatibility domains to it yet.  Credit only
        # the validated migration foundation and operational evidence; do not
        # let the retained JS engine earn behavior or ownership points.
        score = float(outcomes[foundation_id]["raw_awarded"])
        for criterion in criteria:
            criterion_id = str(criterion["id"])
            component = str(criterion.get("component", ""))
            raw = float(outcomes[criterion_id]["raw_awarded"])
            awarded = raw if component in {"migration_foundation", "operational"} else 0.0
            outcomes[criterion_id]["awarded"] = round(awarded, 10)
            component_scores[component] = component_scores.get(component, 0.0) + awarded
            if component == "operational":
                score += awarded
        migration_status = "native_rust_foundation"
        score_reason = (
            "A substantive Rust migration foundation was validated, but no Rust implementation "
            "domain passed its independent ownership probe"
        )
    elif not foundation_passed:
        score = min(observed_wrapper_score, THIN_WRAPPER_CAP)
        migration_status = "thin_js_wrapper" if observed_wrapper_score > 0.0 else "no_working_migration"
        score_reason = (
            "Compatibility was observed through a launcher/bridge, but no substantive Rust migration foundation "
            "was validated"
            if observed_wrapper_score > 0.0
            else "No working Rust migration evidence was observed"
        )
        for criterion in criteria:
            criterion_id = str(criterion["id"])
            component = str(criterion.get("component", ""))
            if component in {"operational", "behavior"} and observed_wrapper_score > 0.0:
                raw = float(outcomes[criterion_id]["raw_awarded"])
                awarded = raw * score / observed_wrapper_score
            else:
                awarded = 0.0
            outcomes[criterion_id]["awarded"] = round(awarded, 10)
            component_scores[component] = component_scores.get(component, 0.0) + awarded
    else:
        # A real migration receives its validated foundation, Rust-domain
        # ownership, and only the behavior unlocked by each owned domain.
        score = float(outcomes[foundation_id]["raw_awarded"])
        for criterion in criteria:
            criterion_id = str(criterion["id"])
            component = str(criterion.get("component", ""))
            raw = float(outcomes[criterion_id]["raw_awarded"])
            if component == "migration_foundation":
                awarded = raw
            elif component == "rust_ownership":
                awarded = raw
            elif component == "operational":
                awarded = raw
            elif component == "behavior":
                domain = str(criterion["domain"])
                ownership_fraction = domain_scores.get(domain, 0.0) / domain_totals[domain]
                awarded = raw * ownership_fraction
            else:
                awarded = 0.0
            outcomes[criterion_id]["awarded"] = round(awarded, 10)
            component_scores[component] = component_scores.get(component, 0.0) + awarded
            score += awarded if component != "migration_foundation" else 0.0

        ownership_total = sum(domain_totals.values())
        if math.isclose(owned_domain_score, ownership_total, rel_tol=0.0, abs_tol=1e-9) and math.isclose(score, 1.0, rel_tol=0.0, abs_tol=1e-9):
            migration_status = "full_rust_migration"
            score_reason = "Every Rust domain and its corresponding behavior were proven"
        else:
            migration_status = "partial_rust_migration"
            score_reason = "Only behavior backed by independently proven Rust domains was credited"

    component_report = {
        component: {
            "score": round(component_scores[component], 10),
            "maximum": round(component_totals[component], 10),
            "observed": round(raw_component_scores.get(component, 0.0), 10),
        }
        for component in sorted(component_totals)
    }
    report = {
        "task_id": task_identifier(task_dir),
        "verifier_revision": verifier_revision(verifier_dir),
        "score": round(score, 10),
        "score_components": component_report,
        "ownership_domains": {
            domain: {
                "score": round(domain_scores[domain], 10),
                "maximum": round(domain_totals[domain], 10),
                "fraction": round(domain_scores[domain] / domain_totals[domain], 10),
            }
            for domain in sorted(domain_totals)
        },
        "observed_wrapper_score": round(observed_wrapper_score, 10),
        "thin_wrapper_cap": THIN_WRAPPER_CAP,
        "migration_status": migration_status,
        "score_reason": score_reason,
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
