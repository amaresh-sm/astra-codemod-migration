import json
import tempfile
import unittest
from pathlib import Path

from astra_harness.generate import (
    OPENHANDS_REASONING_OPTIONS,
    capture_container_diagnostics,
    filtered_openhands_environment,
    gateway_package_version,
    openhands_preflight_script,
    openhands_runtime_environment,
    preserve_failure_diagnostics,
)


class OpenHandsEnvironmentTests(unittest.TestCase):
    def test_filters_to_gateway_keys(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"
            path.write_text(
                "ASTRA_GATEWAY_API_KEY=secret-value\n"
                "ASTRA_GATEWAY_BASE_URL=https://gateway.example/v1\n"
                "UNRELATED_SETTING=must-not-enter-container\n",
                encoding="utf-8",
            )
            path.chmod(0o600)

            self.assertEqual(
                filtered_openhands_environment(path),
                "ASTRA_GATEWAY_API_KEY=secret-value\n"
                "ASTRA_GATEWAY_BASE_URL=https://gateway.example/v1\n",
            )

    def test_rejects_non_private_or_missing_key_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"
            path.write_text("UNRELATED_SETTING=value\n", encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaises(SystemExit):
                filtered_openhands_environment(path)

            path.write_text("ASTRA_GATEWAY_API_KEY=secret-value\n", encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaises(SystemExit):
                filtered_openhands_environment(path)

    def test_runtime_paths_are_workspace_scoped(self) -> None:
        self.assertEqual(
            openhands_runtime_environment(),
            {
                "CARGO_HOME": "/workspace/.cargo-home",
                "CARGO_TARGET_DIR": "/workspace/.cargo-target",
                "TMPDIR": "/workspace/.tmp",
                "YARN_CACHE_FOLDER": "/workspace/.yarn-cache",
            },
        )

    def test_preflight_checks_tools_space_gateway_and_capabilities(self) -> None:
        script = openhands_preflight_script("glm-5.2", "medium")
        for tool in ("cargo", "node", "yarn", "hackerrank-openhands", "rsync", "tmux"):
            self.assertIn(f"missing required tool: $tool", script)
        self.assertIn("df -Pk /workspace", script)
        self.assertIn("df -Pi /workspace", script)
        self.assertIn("/tmp/openhands.env", script)
        self.assertIn("/models", script)
        self.assertIn("model support will be checked by the generation request", script)
        self.assertIn("glm-5.2", script)
        self.assertTrue(all(value in OPENHANDS_REASONING_OPTIONS for value in ("medium", "high")))

    def test_reads_vendored_gateway_version(self) -> None:
        self.assertEqual(gateway_package_version(), "0.1.0")

    def test_failure_diagnostics_retain_workspace_snapshot_and_raw_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = root / "candidate"
            workspace.mkdir()
            source = workspace / "partial.rs"
            source.write_text("fn partial() {}\n", encoding="utf-8")
            workspace_before = {"INSTRUCTION.md": "before-hash"}
            package_output = root / ".openhands-output"
            package_output.mkdir()
            (package_output / "events.jsonl").write_text('{"type":"openhands_event"}\n', encoding="utf-8")

            preserve_failure_diagnostics(root, workspace, workspace_before, package_output)

            snapshot = json.loads(
                (root / "failure-diagnostics/final-workspace-snapshot.json").read_text(encoding="utf-8")
            )
            self.assertEqual(snapshot["final_file_count"], 1)
            self.assertIn("partial.rs", snapshot["files"])
            self.assertTrue((root / "failure-diagnostics/openhands-output/events.jsonl").is_file())

    def test_container_diagnostics_record_not_started_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            logs = Path(raw) / "logs"
            capture_container_diagnostics("unused", logs, started=False)
            self.assertEqual(
                (logs / "docker.log").read_text(encoding="utf-8"),
                "container was not started\n",
            )


if __name__ == "__main__":
    unittest.main()
