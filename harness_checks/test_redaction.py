"""Tests for host-path redaction in persisted harness evidence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from astra_harness.redaction import redact_text, redact_tree


class RedactionTests(unittest.TestCase):
    def test_known_workspace_and_generic_host_paths_are_redacted(self) -> None:
        candidate = Path("/Users/example/work/candidate")
        text = "candidate=/Users/example/work/candidate\ntemp=/private/tmp/run-abc/output.json\n"
        result = redact_text(text, {candidate: "<candidate-workspace>"})
        self.assertIn("<candidate-workspace>", result)
        self.assertIn("<host-path>", result)
        self.assertNotIn("/Users/example", result)
        self.assertNotIn("/private/tmp", result)

    def test_tree_redacts_text_without_touching_binary_files(self) -> None:
        root = Path(tempfile.mkdtemp())
        report = root / "verification.json"
        report.write_text('{"candidate":"/private/tmp/run"}\n')
        binary = root / "screenshot.png"
        binary.write_bytes(b"\x89PNG\r\n\x1a\n")
        changed = redact_tree(root)
        self.assertEqual(changed, [report])
        self.assertNotIn("/private/tmp", report.read_text())
        self.assertEqual(binary.read_bytes(), b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
