"""Convert the migration verifier ledger into the shared normalized scorer format."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CRITERIA = (
    "cli-transform-api", "parser-and-transform-variants", "file-selection-and-stdin",
    "dry-run-print-and-reporting", "parallel-workers-and-results", "failure-and-exit-contract",
    "cli-surface-and-identity", "silent-output-contract", "symlink-boundary",
    "parallel-failure-recovery", "lifecycle-manifest", "custom-option-forwarding",
    "atomic-write-on-error", "parallel-result-determinism", "utf8-source-preservation",
    "ast-collections-and-builders", "ast-formatting-and-comments", "ast-modern-syntax",
    "rust-runner-entrypoint",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.backend.read_text(encoding="utf-8"))
    statuses = payload.get("criterionStatus", {})
    criteria = {}
    for criterion in CRITERIA:
        row = statuses.get(criterion, {})
        status = row.get("status", "blocked") if isinstance(row, dict) else str(row)
        criteria[criterion] = {
            "status": status,
            "score": 1.0 if status == "pass" else 0.0,
            "source": f"migration.{criterion}",
        }
    report = {"schema_version": 1, "criteria": criteria, "evidence": {"backend": str(args.backend)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
