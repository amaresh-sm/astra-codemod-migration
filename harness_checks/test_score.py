import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from astra_harness.score import run


class ScoreTests(unittest.TestCase):
    def make_task(self) -> tuple[Path, Path]:
        root = Path(tempfile.mkdtemp())
        (root / "verifier").mkdir()
        (root / "verifier" / "scoring.yml").write_text(
            "scale: normalized_1\n"
            "criteria:\n"
            "  - id: api\n"
            "    weight: 0.25\n"
            "  - id: workflow\n"
            "    weight: 0.75\n"
        )
        run_dir = root / "run"
        (run_dir / "reports").mkdir(parents=True)
        return root, run_dir

    def test_all_passes_receive_their_weights(self) -> None:
        task, run_dir = self.make_task()
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps({"criteria": {"api": "pass", "workflow": {"status": "pass"}}})
        )
        self.assertEqual(run(SimpleNamespace(task=task, run=run_dir, results=None)), 0)
        report = json.loads((run_dir / "reports" / "score.json").read_text())
        self.assertEqual(report["score"], 1.0)
        self.assertTrue(report["hard_pass"])

    def test_missing_criterion_is_blocked_and_not_a_pass(self) -> None:
        task, run_dir = self.make_task()
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps({"criteria": {"api": "pass"}})
        )
        self.assertEqual(run(SimpleNamespace(task=task, run=run_dir, results=None)), 1)
        report = json.loads((run_dir / "reports" / "score.json").read_text())
        self.assertEqual(report["score"], 0.25)
        self.assertFalse(report["hard_pass"])
        self.assertEqual(report["criteria"]["workflow"]["status"], "blocked")

    def test_fractional_component_score_is_weighted_without_becoming_a_pass(self) -> None:
        task, run_dir = self.make_task()
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps({"criteria": {"api": {"status": "partial", "score": 0.5}, "workflow": "pass"}})
        )
        self.assertEqual(run(SimpleNamespace(task=task, run=run_dir, results=None)), 1)
        report = json.loads((run_dir / "reports" / "score.json").read_text())
        self.assertEqual(report["score"], 0.875)
        self.assertFalse(report["hard_pass"])
        self.assertEqual(report["criteria"]["api"]["awarded"], 0.125)

    def test_out_of_range_fraction_is_rejected(self) -> None:
        task, run_dir = self.make_task()
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps({"criteria": {"api": {"status": "partial", "score": 1.1}}})
        )
        with self.assertRaises(SystemExit):
            run(SimpleNamespace(task=task, run=run_dir, results=None))


if __name__ == "__main__":
    unittest.main()
