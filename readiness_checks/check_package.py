#!/usr/bin/env python3
"""Check the public/private boundary and required task-package layout."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path
from typing import Any, Iterable

try:
    from .common import emit_result
except ImportError:  # Direct execution: ``python readiness_checks/check_package.py``.
    from common import emit_result


# These names identify evaluator material.  Do not reject ordinary words such as
# "reference" or "score"; public contracts may use them as product terminology.
PRIVATE_PATH_PARTS = {
    "verifier",
    "hidden-tests",
    "hidden_tests",
    "mutants",
    "reference-solution",
    "reference_solution",
    "proof-of-work",
    "proof_of_work",
    "acceptance-criteria.yml",
    "acceptance_criteria.yml",
    "scoring.yml",
    "scoring.yaml",
    ".env",
    "auth.json",
}

PRIVATE_TEXT = (
    re.compile(r"\bhidden[ _-]?tests?\b", re.IGNORECASE),
    re.compile(r"\bmutants?\b", re.IGNORECASE),
    re.compile(r"\breference[ _-]?solutions?\b", re.IGNORECASE),
    re.compile(r"\b(?:acceptance[ _-]?criteria|proof[ _-]?of[ _-]?work)\b", re.IGNORECASE),
    re.compile(r"(?:^|[/'`])verifier(?:[/`]|$)", re.IGNORECASE),
    re.compile(r"\b(?:readiness|harness)[_-]?checks?\b", re.IGNORECASE),
)

# /workspace is an intentional container path in the public handoff.  These are
# host-local paths that should never be baked into candidate-facing material.
LOCAL_PATH = re.compile(
    r"(?:file://)?/(?:Users/|home/[^/]+/|private/tmp/|private/var/|var/folders/)",
)
SECRET_VALUE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk|pk)-(?:live|test)-[A-Za-z0-9_-]{12,}",
    re.IGNORECASE,
)


def _files(root: Path) -> Iterable[Path]:
    """Yield regular files below ``root`` without following directory symlinks."""

    if not root.is_dir():
        return ()
    return (path for path in root.rglob("*") if path.is_file())


def _scan_public(task_dir: Path) -> list[str]:
    """Return boundary violations found in candidate-visible files."""

    violations: list[str] = []
    visible = [task_dir / "instruction.md", *list(_files(task_dir / "public"))]
    for path in visible:
        if not path.is_file():
            continue
        relative = path.relative_to(task_dir)
        if path.is_symlink():
            violations.append(f"symbolic link is not allowed: {relative}")
        parts = {part.lower() for part in relative.parts}
        private_parts = sorted(parts & {part.lower() for part in PRIVATE_PATH_PARTS})
        for part in private_parts:
            violations.append(f"private path component {part!r}: {relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary public assets cannot contain readable evaluator instructions.
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if LOCAL_PATH.search(line):
                violations.append(f"host-local path at {relative}:{line_number}")
            if SECRET_VALUE.search(line):
                violations.append(f"secret-like value at {relative}:{line_number}")
            for pattern in PRIVATE_TEXT:
                if pattern.search(line):
                    violations.append(f"private evaluator reference at {relative}:{line_number}")
                    break
    return violations


def _missing_paths(task_dir: Path, verifier_dir: Path) -> list[str]:
    """Return required package paths that are absent."""

    try:
        profile = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8")).get("profile")
    except (OSError, tomllib.TOMLDecodeError):
        profile = None
    contract = (
        task_dir / "public/contracts/migration.contract.json"
        if profile == "migration"
        else task_dir / "public/contracts/openapi.contract.json"
    )
    required_files = [
        task_dir / "task.toml",
        task_dir / "instruction.md",
        contract,
        verifier_dir / "run.py",
        verifier_dir / "score_adapter.py",
        verifier_dir / "acceptance-criteria.yml",
        verifier_dir / "scoring.yml",
        verifier_dir / "reference-solution/app-setup/manifest.json",
        verifier_dir / "reference-solution/app-setup/build.sh",
        verifier_dir / "reference-solution/app-setup/start.sh",
        verifier_dir / "reference-solution/app-setup/reset.sh",
    ]
    required_dirs = [
        task_dir / "public",
        task_dir / "public/contracts",
        verifier_dir,
        verifier_dir / "hidden-tests",
        verifier_dir / "mutants",
        verifier_dir / "reference-solution",
        verifier_dir / "proof-of-work",
        verifier_dir / "reference-solution/app-setup",
    ]
    missing = [str(path) for path in required_files if not path.is_file()]
    missing.extend(str(path) for path in required_dirs if not path.is_dir())
    return missing


def check_package(task_dir: Path, verifier_dir: Path) -> dict[str, Any]:
    """Validate candidate visibility and the task's private package layout."""

    task_dir = task_dir.resolve()
    verifier_dir = verifier_dir.resolve()
    public_violations = _scan_public(task_dir)
    missing = _missing_paths(task_dir, verifier_dir)
    result: dict[str, Any] = {
        "check": "package-boundary-and-layout",
        "task_dir": str(task_dir),
        "verifier_dir": str(verifier_dir),
        "public_violations": public_violations,
        "missing_paths": missing,
        "failures": [],
    }
    result["failures"].extend(f"public boundary: {item}" for item in public_violations)
    result["failures"].extend(f"missing required path: {item}" for item in missing)
    result["ok"] = not result["failures"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, default=Path("tasks"))
    parser.add_argument("--verifier-dir", type=Path, default=Path("verifier"))
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args()
    result = check_package(args.task_dir, args.verifier_dir)
    emit_result(result, args.json)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
