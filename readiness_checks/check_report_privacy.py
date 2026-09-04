#!/usr/bin/env python3
"""Reject persisted run evidence that leaks absolute paths from an author's host."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from .check_package import LOCAL_PATH
    from .common import emit_result
except ImportError:
    from check_package import LOCAL_PATH
    from common import emit_result


EVIDENCE_ROOTS = (Path("candidates"), Path("verifier/proof-of-work"))


def _evidence_roots(repository_root: Path) -> list[Path]:
    """Return only generated evidence, never candidate or verifier source."""

    roots: list[Path] = []
    candidates = repository_root / "candidates"
    if candidates.is_dir():
        roots.extend(path for path in candidates.glob("*/evaluation-*") if path.is_dir())
    proof = repository_root / "verifier/proof-of-work"
    if proof.is_dir():
        roots.extend(path for path in proof.iterdir() if path.is_dir())
    return roots


def check_report_privacy(repository_root: Path) -> dict[str, Any]:
    """Find readable report/log evidence containing a host-local path."""

    failures: list[str] = []
    for root in _evidence_roots(repository_root):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if LOCAL_PATH.search(line):
                    failures.append(f"host-local path at {path.relative_to(repository_root)}:{line_number}")
                    break
    return {
        "check": "persisted-report-privacy",
        "failures": failures,
        "ok": not failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_report_privacy(args.repository_root.resolve())
    emit_result(result, args.json)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
