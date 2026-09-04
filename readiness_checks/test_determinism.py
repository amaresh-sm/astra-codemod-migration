"""Tests for repeated reference-run determinism checks."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from check_determinism import check_determinism


class DeterminismReadinessTests(unittest.TestCase):
    def _run(self, root: Path, name: str, status: str = "passed") -> None:
        run = root / "reference-runs" / name / "reports"
        (run / "backend").mkdir(parents=True, exist_ok=True)
        (run / "ui").mkdir(parents=True, exist_ok=True)
        (run / "backend/reward.json").write_text(
            json.dumps({"criterionStatus": {"AC-1": {"status": status}}})
        )
        (run / "ui/ui-reward.json").write_text(
            json.dumps({"capabilities": [{"id": "ui-1", "status": status}]})
        )
        (run / "score.json").write_text(
            json.dumps({"score": 1.0, "hard_pass": True, "criteria": {"a": {"status": "pass"}}})
        )

    def test_equal_reference_runs_pass(self) -> None:
        root = Path(tempfile.mkdtemp())
        self._run(root, "one")
        self._run(root, "two")
        self.assertTrue(check_determinism(root)["ok"])

    def test_different_criterion_outcome_fails(self) -> None:
        root = Path(tempfile.mkdtemp())
        self._run(root, "one")
        self._run(root, "two", status="failed")
        result = check_determinism(root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("differ" in item for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
