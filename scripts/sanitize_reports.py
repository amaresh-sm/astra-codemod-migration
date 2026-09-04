#!/usr/bin/env python3
"""Sanitize persisted run evidence so it never exposes an author's host paths."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The script is deliberately executable directly from the repository root,
# without requiring authors to install the harness as a package first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astra_harness.redaction import redact_tree


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="run-evidence directories to sanitize")
    return parser.parse_args()


def _candidate_id(metadata_path: Path) -> str:
    """Derive a stable label from the evidence directory, never a host path."""

    run_dir = metadata_path.parent
    if run_dir.name.startswith("evaluation-"):
        return run_dir.parent.name
    return run_dir.name


def normalize_verification_metadata(root: Path) -> list[Path]:
    """Migrate old verification reports away from the host ``candidate`` field."""

    changed: list[Path] = []
    if not root.is_dir():
        return changed
    for path in root.rglob("verification.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict) or "candidate" not in metadata:
            continue
        metadata.pop("candidate")
        metadata.setdefault("candidate_id", _candidate_id(path))
        metadata["workspace"] = "<candidate-workspace>"
        path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        changed.append(path)
    return changed


def main() -> int:
    args = parse_args()
    changed: list[Path] = []
    for root in args.paths:
        changed.extend(redact_tree(root))
        changed.extend(normalize_verification_metadata(root))
    print(f"Sanitized {len(changed)} evidence file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
