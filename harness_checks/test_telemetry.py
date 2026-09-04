"""Unit tests for provider-neutral generation telemetry."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from astra_harness.telemetry import collect, snapshot_workspace


class TelemetryTests(unittest.TestCase):
    def test_collects_size_usage_and_structured_tool_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text("print('before')\n", encoding="utf-8")
            before = snapshot_workspace(root)
            (root / "app.py").write_text("print('after')\nprint('done')\n", encoding="utf-8")
            (root / "feature.ts").write_text("export const ready = true;\n", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")
            log = root / "generation.log"
            log.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
                        json.dumps({"type": "item.completed", "item": {"type": "file_change"}}),
                        json.dumps({"type": "result", "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 2}}),
                    ]
                ),
                encoding="utf-8",
            )

            telemetry = collect(root, before, log)

            self.assertEqual(telemetry["tokens"]["total"], 17)
            self.assertEqual(telemetry["tokens"]["source"], "provider-reported")
            self.assertEqual(telemetry["tool_calls"]["total"], 2)
            self.assertEqual(telemetry["tool_calls"]["by_type"]["shell"], 1)
            self.assertEqual(telemetry["tool_calls"]["by_type"]["edit"], 1)
            self.assertEqual(telemetry["solution_size"]["workspace_source_files"], 2)
            self.assertEqual(telemetry["solution_size"]["agent_changed_source_files"], 2)

    def test_recognizes_claude_stream_tool_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "generation.log"
            log.write_text(
                json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}}),
                encoding="utf-8",
            )

            telemetry = collect(root, snapshot_workspace(root), log)

            self.assertEqual(telemetry["tool_calls"]["total"], 1)
            self.assertEqual(telemetry["tool_calls"]["by_type"]["read"], 1)

    def test_marks_plain_logs_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.py").write_text("pass\n", encoding="utf-8")
            log = root / "generation.log"
            log.write_text("agent completed\n", encoding="utf-8")

            telemetry = collect(root, snapshot_workspace(root), log)

            self.assertEqual(telemetry["tokens"]["source"], "unavailable")
            self.assertEqual(telemetry["tool_calls"]["source"], "unavailable")
