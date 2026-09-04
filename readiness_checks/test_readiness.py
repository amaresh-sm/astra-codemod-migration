"""Unit tests for the deterministic reference and mutant readiness gates."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from check_mutants import check_mutants
from check_reference import check_reference


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def score(*, value: float = 1.0, hard_pass: bool = True, criteria: dict | None = None) -> dict:
    return {
        "score": value,
        "hard_pass": hard_pass,
        "criteria": criteria or {"backend-behavior": {"status": "pass"}},
    }


def reward(statuses: dict[str, str]) -> dict:
    return {
        "criterionStatus": {
            key: {"status": value, "scenarioId": "backend.example"}
            for key, value in statuses.items()
        }
    }


class ReferenceGateTests(unittest.TestCase):
    def test_requires_a_complete_one_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory)
            write_json(proof / "reference-runs/r1/reports/score.json", score())
            result = check_reference(proof)
            self.assertTrue(result["ok"])

            write_json(proof / "reference-runs/r1/reports/score.json", score(value=0.9, hard_pass=False))
            result = check_reference(proof)
            self.assertFalse(result["ok"])
            self.assertTrue(any("score is" in failure for failure in result["failures"]))


class MutantCoverageTests(unittest.TestCase):
    def _build_fixture(self, *, unrelated: bool = False) -> Path:
        root = Path(tempfile.mkdtemp())
        write_json(
            root / "verifier/proof-of-work/reference-runs/r1/reports/backend/reward.json",
            reward({"AC-EXPECTED": "passed", "AC-OTHER": "passed"}),
        )
        write_json(
            root / "verifier/proof-of-work/mutant-runs/example/reports/backend/reward.json",
            reward(
                {
                    "AC-EXPECTED": "failed",
                    "AC-OTHER": "failed" if unrelated else "passed",
                }
            ),
        )
        write_json(
            root / "verifier/proof-of-work/mutant-runs/example/reports/score.json",
            score(value=0.5, hard_pass=False),
        )
        write_json(
            root / "verifier/proof-of-work/mutant-runs/example/verification.json",
            {"status": "passed"},
        )
        run_patch = root / "verifier/proof-of-work/mutant-runs/example/mutant.patch"
        run_patch.parent.mkdir(parents=True, exist_ok=True)
        run_patch.write_text("diff --git a/app b/app\n", encoding="utf-8")
        patch = root / "verifier/mutants/example.patch"
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text("diff --git a/app b/app\n", encoding="utf-8")
        write_json(
            root / "verifier/proof-of-work/mutant-matrix.json",
            {
                "mutants": {
                    "example": {
                        "hidden_test": "backend.example",
                        "expected_criteria": ["AC-EXPECTED"],
                    }
                }
            },
        )
        return root

    def test_requires_expected_regression_and_rejects_unrelated_regression(self) -> None:
        root = self._build_fixture()
        try:
            result = check_mutants(root / "verifier", root / "verifier/proof-of-work")
            self.assertTrue(result["ok"])

            root = self._build_fixture(unrelated=True)
            result = check_mutants(root / "verifier", root / "verifier/proof-of-work")
            self.assertFalse(result["ok"])
            self.assertTrue(any("unrelated criteria" in failure for failure in result["failures"]))
        finally:
            # Temporary directories are intentionally left to the OS; no repository files are touched.
            pass


if __name__ == "__main__":
    unittest.main()
