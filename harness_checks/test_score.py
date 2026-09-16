import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from astra_harness.score import run


class ScoreTests(unittest.TestCase):
    SCORING = (
        "scale: normalized_1\n"
        "criteria:\n"
        "  - id: operational\n"
        "    component: operational\n"
        "    weight: 0.10\n"
        "  - id: behavior\n"
        "    component: behavior\n"
        "    domain: ast\n"
        "    weight: 0.20\n"
        "  - id: rust-runner-entrypoint\n"
        "    component: migration_foundation\n"
        "    domain: foundation\n"
        "    weight: 0.10\n"
        "  - id: ownership\n"
        "    component: rust_ownership\n"
        "    domain: ast\n"
        "    weight: 0.60\n"
    )

    def make_task(self) -> tuple[Path, Path]:
        root = Path(tempfile.mkdtemp())
        (root / "verifier").mkdir()
        (root / "verifier" / "scoring.yml").write_text(self.SCORING)
        run_dir = root / "run"
        (run_dir / "reports").mkdir(parents=True)
        return root, run_dir

    def test_thin_wrapper_is_capped_but_keeps_observed_evidence(self) -> None:
        root, run_dir = self.make_task()
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps(
                {
                    "criteria": {
                        "operational": "pass",
                        "behavior": "pass",
                        "rust-runner-entrypoint": "fail",
                        "ownership": "fail",
                    }
                }
            )
        )

        self.assertEqual(run(SimpleNamespace(task=root, run=run_dir, results=None)), 1)
        report = json.loads((run_dir / "reports" / "score.json").read_text())
        self.assertEqual(report["score"], 0.04)
        self.assertEqual(report["migration_status"], "thin_js_wrapper")
        self.assertEqual(report["observed_wrapper_score"], 0.3)
        self.assertEqual(report["score_components"]["behavior"]["observed"], 0.2)
        self.assertEqual(report["score_components"]["rust_ownership"]["score"], 0.0)

    def test_bridge_boundary_does_not_veto_an_independent_rust_domain(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "verifier").mkdir()
        (root / "verifier" / "scoring.yml").write_text(
            self.SCORING.replace("    weight: 0.60\n", "    weight: 0.50\n")
            + "  - id: rust-legacy-engine-boundary\n"
            "    component: rust_ownership\n"
            "    domain: cli\n"
            "    weight: 0.10\n"
        )
        run_dir = root / "run"
        (run_dir / "reports").mkdir(parents=True)
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps(
                {
                    "criteria": {
                        "operational": "pass",
                        "behavior": "pass",
                        "rust-runner-entrypoint": "pass",
                        "ownership": "pass",
                        "rust-legacy-engine-boundary": "fail",
                    }
                }
            )
        )

        self.assertEqual(run(SimpleNamespace(task=root, run=run_dir, results=None)), 1)
        report = json.loads((run_dir / "reports" / "score.json").read_text())
        self.assertEqual(report["score"], 0.9)
        self.assertEqual(report["migration_status"], "partial_rust_migration")
        self.assertEqual(report["score_components"]["migration_foundation"]["score"], 0.1)
        self.assertEqual(report["score_components"]["behavior"]["score"], 0.2)
        self.assertEqual(report["score_components"]["rust_ownership"]["score"], 0.5)

    def test_all_passes_receive_their_weights(self) -> None:
        task, run_dir = self.make_task()
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps(
                {
                    "criteria": {
                        "operational": "pass",
                        "behavior": "pass",
                        "rust-runner-entrypoint": "pass",
                        "ownership": "pass",
                    }
                }
            )
        )
        self.assertEqual(run(SimpleNamespace(task=task, run=run_dir, results=None)), 0)
        report = json.loads((run_dir / "reports" / "score.json").read_text())
        self.assertEqual(report["score"], 1.0)
        self.assertTrue(report["hard_pass"])

    def test_missing_criterion_is_blocked_and_not_a_pass(self) -> None:
        task, run_dir = self.make_task()
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps({"criteria": {"operational": "pass"}})
        )
        self.assertEqual(run(SimpleNamespace(task=task, run=run_dir, results=None)), 1)
        report = json.loads((run_dir / "reports" / "score.json").read_text())
        self.assertEqual(report["score"], 0.04)
        self.assertFalse(report["hard_pass"])
        self.assertEqual(report["criteria"]["behavior"]["status"], "blocked")

    def test_fractional_component_score_is_weighted_without_becoming_a_pass(self) -> None:
        task, run_dir = self.make_task()
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps(
                {
                    "criteria": {
                        "operational": "pass",
                        "behavior": "pass",
                        "rust-runner-entrypoint": "pass",
                        "ownership": {"status": "partial", "score": 0.5},
                    }
                }
            )
        )
        self.assertEqual(run(SimpleNamespace(task=task, run=run_dir, results=None)), 1)
        report = json.loads((run_dir / "reports" / "score.json").read_text())
        self.assertEqual(report["score"], 0.6)
        self.assertFalse(report["hard_pass"])
        self.assertEqual(report["criteria"]["behavior"]["awarded"], 0.1)

    def test_out_of_range_fraction_is_rejected(self) -> None:
        task, run_dir = self.make_task()
        (run_dir / "reports" / "criteria.json").write_text(
            json.dumps({"criteria": {"ownership": {"status": "partial", "score": 1.1}}})
        )
        with self.assertRaises(SystemExit):
            run(SimpleNamespace(task=task, run=run_dir, results=None))


if __name__ == "__main__":
    unittest.main()
