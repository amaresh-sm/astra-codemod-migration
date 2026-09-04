"""Tests for scoring schema and blocked-result readiness checks."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from check_scoring import check_scoring


class ScoringReadinessTests(unittest.TestCase):
    def _layout(self, scoring: str) -> tuple[Path, Path]:
        root = Path(tempfile.mkdtemp())
        verifier = root / "verifier"
        proof = verifier / "proof-of-work"
        (proof / "candidate-runs/r1/reports").mkdir(parents=True)
        verifier.mkdir(exist_ok=True)
        (verifier / "scoring.yml").write_text(scoring)
        return verifier, proof

    def test_valid_weights_and_blocked_zero_pass(self) -> None:
        verifier, proof = self._layout(
            "scale: normalized_1\ncriteria:\n  - id: a\n    weight: 1.0\n"
        )
        (proof / "candidate-runs/r1/reports/score.json").write_text(
            json.dumps({"criteria": {"a": {"status": "blocked", "score": 0, "awarded": 0}}})
        )
        self.assertTrue(check_scoring(verifier, proof)["ok"])

    def test_blocked_nonzero_award_fails(self) -> None:
        verifier, proof = self._layout(
            "scale: normalized_1\ncriteria:\n  - id: a\n    weight: 1.0\n"
        )
        (proof / "candidate-runs/r1/reports/score.json").write_text(
            json.dumps({"criteria": {"a": {"status": "blocked", "score": 1, "awarded": 1}}})
        )
        result = check_scoring(verifier, proof)
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked_result_violations"])


if __name__ == "__main__":
    unittest.main()
