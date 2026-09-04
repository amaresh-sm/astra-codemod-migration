"""Tests for the public/private boundary and package-layout readiness gate."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from check_package import check_package


class PackageReadinessTests(unittest.TestCase):
    def _package(self) -> tuple[Path, Path]:
        root = Path(tempfile.mkdtemp())
        task = root / "tasks"
        verifier = root / "verifier"
        for path in (
            task / "public/contracts",
            verifier / "hidden-tests",
            verifier / "mutants",
            verifier / "proof-of-work",
            verifier / "reference-solution/app-setup",
        ):
            path.mkdir(parents=True, exist_ok=True)
        (task / "task.toml").write_text('id = "example"\nprofile = "greenfield"\ntitle = "Example"\n')
        (task / "instruction.md").write_text("Build the application.\n")
        (task / "public/contracts/openapi.contract.json").write_text("{}\n")
        (task / "public/contracts/ui.contract.json").write_text("{}\n")
        for name in ("run.py", "score_adapter.py", "acceptance-criteria.yml", "scoring.yml"):
            (verifier / name).write_text("placeholder\n")
        for name in ("manifest.json", "build.sh", "start.sh", "reset.sh"):
            (verifier / "reference-solution/app-setup" / name).write_text("placeholder\n")
        return task, verifier

    def test_complete_package_passes(self) -> None:
        task, verifier = self._package()
        result = check_package(task, verifier)
        self.assertTrue(result["ok"], result["failures"])

    def test_private_material_and_host_path_are_rejected(self) -> None:
        task, verifier = self._package()
        (task / "public/README.md").write_text(
            "See hidden tests in /Users/example/project and verifier/mutants.\n"
        )
        result = check_package(task, verifier)
        self.assertFalse(result["ok"])
        self.assertGreaterEqual(len(result["public_violations"]), 2)

    def test_missing_app_setup_is_rejected(self) -> None:
        task, verifier = self._package()
        (verifier / "reference-solution/app-setup/reset.sh").unlink()
        result = check_package(task, verifier)
        self.assertFalse(result["ok"])
        self.assertTrue(any(item.endswith("reset.sh") for item in result["missing_paths"]))


if __name__ == "__main__":
    unittest.main()
