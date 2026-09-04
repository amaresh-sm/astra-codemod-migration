"""Tests for proof-of-work evidence validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from check_proof_work import check_proof_work


class ProofWorkTests(unittest.TestCase):
    def test_requires_repeated_reference_and_frontier_runs(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "verifier/proof-of-work/reference-runs").mkdir(parents=True)
        (root / "verifier/proof-of-work/candidate-runs").mkdir(parents=True)
        (root / "verifier/proof-of-work/mutant-runs").mkdir(parents=True)
        (root / "verifier/mutants").mkdir(parents=True)
        result = check_proof_work(root / "verifier", root / "verifier/proof-of-work")
        self.assertFalse(result["ok"])
        self.assertTrue(any("two reference runs" in item for item in result["failures"]))
        self.assertTrue(any("two frontier-model" in item for item in result["failures"]))

    def test_candidate_metadata_and_scores_are_accepted(self) -> None:
        root = Path(tempfile.mkdtemp())
        proof = root / "verifier/proof-of-work"
        verifier = root / "verifier"
        for name in ("one", "two"):
            run = proof / "candidate-runs" / name
            (run / "reports").mkdir(parents=True)
            (run / "provenance.json").write_text(json.dumps({
                "source_run_id": name, "provider": "codex", "model": "frontier",
                "reasoning": "high", "generation_elapsed_seconds": 10,
                "source_exit_code": 0, "source_tamper_check": "clean",
            }))
            (run / "verification.json").write_text(json.dumps({"status": "passed", "exit_code": 0}))
            (run / "score.json").write_text(json.dumps({"score": 0.5, "hard_pass": False}))
        for name in ("r1", "r2"):
            run = proof / "reference-runs" / name
            (run / "reports").mkdir(parents=True)
            metadata = {"task_id": "task", "status": "passed", "started_at": "t",
                        "finished_at": "t", "duration_seconds": 1, "exit_code": 0}
            (run / "verification.json").write_text(json.dumps(metadata))
            (run / "reports/score.json").write_text(json.dumps({"score": 1.0, "hard_pass": True, "criteria": {"a": {"status": "pass"}}}))
        matrix = proof / "mutant-matrix.json"
        (verifier / "mutants").mkdir(parents=True)
        (verifier / "scoring.yml").parent.mkdir(parents=True, exist_ok=True)
        (verifier / "mutants/example.patch").write_text("patch")
        mutant = proof / "mutant-runs/example"
        (mutant / "reports/backend").mkdir(parents=True)
        (mutant / "mutant.patch").write_text("patch")
        (mutant / "verification.json").write_text(json.dumps({
            "task_id": "task", "status": "passed", "started_at": "t",
            "finished_at": "t", "duration_seconds": 1, "exit_code": 0,
        }))
        (mutant / "reports/score.json").write_text(json.dumps({"score": 0.5, "hard_pass": False}))
        (mutant / "reports/backend/reward.json").write_text("{}")
        matrix.write_text(json.dumps({"mutants": {"example": {}}}))
        result = check_proof_work(verifier, proof)
        self.assertTrue(result["ok"], result["failures"])


if __name__ == "__main__":
    unittest.main()
