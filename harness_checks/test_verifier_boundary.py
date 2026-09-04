"""Static boundary checks for the two-container verification design."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VerifierBoundaryTests(unittest.TestCase):
    def test_candidate_runtime_never_receives_private_verifier_mount(self) -> None:
        source = (ROOT / "astra_harness/verify.py").read_text(encoding="utf-8")
        runtime_section = source.split("docker_args =", 1)[0]
        self.assertNotIn("/input/verifier", runtime_section)
        self.assertIn('"--network", f"container:{runtime_name}"', source)
        self.assertIn('"--cap-drop", "NET_RAW"', source)

    def test_verifier_entrypoint_never_executes_candidate_commands(self) -> None:
        source = (ROOT / "environment/verifier/entrypoint.sh").read_text(encoding="utf-8")
        self.assertNotIn("/work/candidate", source)
        self.assertIn("cd /input/verifier", source)
        self.assertIn("Candidate lifecycle commands run only", source)


if __name__ == "__main__":
    unittest.main()
