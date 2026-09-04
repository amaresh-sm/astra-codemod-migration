"""Shared helpers for deterministic task-package readiness checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object and provide a useful error for malformed evidence."""

    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def status_value(value: Any) -> str:
    """Return a normalized criterion status from either supported evidence shape."""

    if isinstance(value, dict):
        value = value.get("status")
    return str(value or "").strip().lower()


PASS_STATUSES = frozenset({"pass", "passed", "pass_with_evidence"})


def emit_result(result: dict[str, Any], as_json: bool) -> None:
    """Print a stable human or machine-readable readiness result."""

    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    state = "PASS" if result.get("ok") else "FAIL"
    print(f"{state}: {result.get('check', 'readiness check')}")
    for failure in result.get("failures", []):
        print(f"- {failure}")

