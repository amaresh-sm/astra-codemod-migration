"""Tests for the persisted-evidence host-path readiness gate."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from check_report_privacy import check_report_privacy


class ReportPrivacyTests(unittest.TestCase):
    def test_clean_evidence_passes(self) -> None:
        root = Path(tempfile.mkdtemp())
        evidence = root / "candidates/example/reports"
        evidence.mkdir(parents=True)
        (evidence / "score.json").write_text('{"workspace":"<candidate-workspace>"}\n')
        self.assertTrue(check_report_privacy(root)["ok"])

    def test_host_path_fails(self) -> None:
        root = Path(tempfile.mkdtemp())
        evidence = root / "verifier/proof-of-work/reference-runs/example"
        evidence.mkdir(parents=True)
        (evidence / "verification.json").write_text('{"candidate":"/private/tmp/example"}\n')
        result = check_report_privacy(root)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["failures"]), 1)


if __name__ == "__main__":
    unittest.main()
