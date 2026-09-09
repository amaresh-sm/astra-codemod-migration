"""Run black-box migration checks against the submitted jscodeshift CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jscodeshift_checks import SCENARIO_IDS, check as genuine_check


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    # The shared verifier runner owns lifecycle execution. Keep this flag for
    # compatibility with the external-lifecycle handoff, but do not let it
    # change the black-box test surface.
    parser.add_argument("--external-lifecycle", action="store_true")
    args = parser.parse_args()

    statuses = genuine_check(args.candidate.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    passed = all(value["status"] == "pass" for value in statuses.values())
    report = {
        "criterionStatus": {
            key: {
                "status": value["status"],
                "scenarioId": SCENARIO_IDS[key],
                "detail": value["detail"],
            }
            for key, value in statuses.items()
        },
        "status": "pass" if passed else "fail",
    }
    backend = args.output / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    (backend / "reward.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.output / "criteria.json").write_text(
        json.dumps({"criteria": statuses}, indent=2) + "\n", encoding="utf-8"
    )
    # A criterion failure is a scored candidate result, not a verifier
    # infrastructure failure. The harness needs a successful verifier exit so
    # it can retain criteria.json and let the scoring phase mark hard_pass
    # false. Exceptions still propagate as verifier failures.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
