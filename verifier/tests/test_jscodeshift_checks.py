import tempfile
import unittest
import json
from pathlib import Path

from verifier.jscodeshift_checks import (
    _remove_non_bridge_sources,
    allowed_js_bridge_paths,
    bridge_engine_findings,
    cli_command,
    cli_path,
    legacy_engine_module_patterns,
    legacy_engine_paths,
    rust_migration_progress_evidence,
    retained_legacy_engine_copies,
    substantive_rust_migration_evidence,
)


class MigrationOwnershipTests(unittest.TestCase):
    def test_cli_path_uses_package_declared_bin_over_legacy_filename(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            candidate = Path(raw) / "candidate"
            candidate.mkdir()
            (candidate / "package.json").write_text(
                json.dumps({"bin": {"jscodeshift": "bin/jscodeshift-rust.js"}}),
                encoding="utf-8",
            )
            (candidate / "bin").mkdir()
            (candidate / "bin/jscodeshift.js").write_text("legacy\n", encoding="utf-8")
            declared = candidate / "bin/jscodeshift-rust.js"
            declared.write_text("native launcher\n", encoding="utf-8")

            self.assertEqual(cli_path(candidate), declared)
            self.assertEqual(cli_command(candidate), ["node", str(declared)])

    def test_bridge_engine_audit_rejects_hybrid_ast_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            candidate = Path(raw) / "candidate"
            (candidate / "app-setup").mkdir(parents=True)
            (candidate / "app-setup/manifest.json").write_text(
                '{"javascriptBridge":"rust-compat.js"}', encoding="utf-8"
            )
            (candidate / "rust-compat.js").write_text(
                "const api = {};\n"
                "api['find'] = () => {}; api['replaceWith'] = () => {}; api['toSource'] = () => {};\n"
                "const node = { type: 'Identifier', name: 'value' };\n"
                "function lift() { return node; }\n",
                encoding="utf-8",
            )

            findings = bridge_engine_findings(candidate)

            self.assertEqual(len(findings), 1)
            self.assertIn("collection runtime", findings[0])
            self.assertIn("AST builders", findings[0])

    def test_bridge_engine_audit_allows_loader_only_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            candidate = Path(raw) / "candidate"
            (candidate / "app-setup").mkdir(parents=True)
            (candidate / "app-setup/manifest.json").write_text(
                '{"javascriptBridge":"rust-compat.js"}', encoding="utf-8"
            )
            (candidate / "rust-compat.js").write_text(
                "const { spawnSync } = require('child_process');\n"
                "module.exports = request => spawnSync(process.env.JSCODESHIFT_NATIVE_ENGINE, [], { input: request });\n",
                encoding="utf-8",
            )

            self.assertEqual(bridge_engine_findings(candidate), [])

    def test_bridge_only_cleanup_removes_renamed_implementation_sources(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / "candidate"
            package.mkdir()
            (package / "app-setup").mkdir()
            (package / "app-setup/manifest.json").write_text(
                '{"javascriptBridge":["rust-compat.js"]}', encoding="utf-8"
            )
            (package / "rust-compat.js").write_text("module.exports = {};\n", encoding="utf-8")
            (package / "lib/renamed-engine.js").parent.mkdir(parents=True)
            (package / "lib/renamed-engine.js").write_text("module.exports = {};\n", encoding="utf-8")
            (package / "src/parser.ts").parent.mkdir(parents=True)
            (package / "src/parser.ts").write_text("export const parser = true;\n", encoding="utf-8")

            removed = _remove_non_bridge_sources(package)

            self.assertEqual(set(removed), {"lib/renamed-engine.js", "src/parser.ts"})
            self.assertTrue((package / "rust-compat.js").is_file())
            self.assertEqual(allowed_js_bridge_paths(package), {"rust-compat.js"})

    def test_reference_bridge_is_reported_as_engine_logic(self) -> None:
        reference = Path(__file__).parents[1] / "reference-solution"
        findings = bridge_engine_findings(reference)
        self.assertTrue(findings)
        self.assertTrue(any("rust-compat.js" in finding for finding in findings))

    def test_rust_foundation_requires_real_implementation_not_a_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = root / "rust/Cargo.toml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("[package]\nname = 'candidate'\nversion = '0.1.0'\n")
            source = manifest.parent / "src/main.rs"
            source.parent.mkdir()
            source.write_text("fn main() { println!(\"launcher\"); }\n")

            passed, detail = substantive_rust_migration_evidence(root, [manifest])

            self.assertFalse(passed)
            self.assertIn("not backed by a substantive migration foundation", detail)

    def test_rust_foundation_accepts_substantial_semantic_migration_work(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = root / "rust/Cargo.toml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("[package]\nname = 'candidate'\nversion = '0.1.0'\n")
            source_dir = manifest.parent / "src"
            source_dir.mkdir()
            modules = {
                "args.rs": "pub fn parse() { let _ = std::env::args(); }\n",
                "files.rs": "pub fn discover() { let _ = std::fs::read_dir(\".\"); }\n",
                "runner.rs": "pub fn run() { let _ = std::process::Command::new(\"true\"); }\n",
            }
            for name, line in modules.items():
                (source_dir / name).write_text(line * 150)

            passed, detail = substantive_rust_migration_evidence(root, [manifest])

            self.assertTrue(passed)
            self.assertIn("substantive Rust migration foundation", detail)

    def test_migration_progress_requires_complete_subsystem_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = root / "rust/Cargo.toml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("[package]\nname = 'candidate'\nversion = '0.1.0'\n")
            source = manifest.parent / "src/runner.rs"
            source.parent.mkdir()
            # Generic I/O and a package-shaped identifier must not earn
            # atomic-write or package-integration migration credit.
            source.write_text(
                ("fn helper() { let package_info = 1; let _ = package_info; "
                 "let _ = std::fs::OpenOptions::new(); }\n") * 50,
                encoding="utf-8",
            )

            score, detail = rust_migration_progress_evidence(root, [manifest])

            self.assertEqual(score, 0.0)
            self.assertIn("no scored subsystems", detail)

    def test_migration_progress_recognizes_atomic_write_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = root / "rust/Cargo.toml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("[package]\nname = 'candidate'\nversion = '0.1.0'\n")
            source = manifest.parent / "src/atomic_write.rs"
            source.parent.mkdir()
            source.write_text(
                (
                    "fn atomic_write(temporary: &std::path::Path, target: &std::path::Path, "
                    "bytes: &[u8]) { let mut file = std::fs::File::create(temporary).unwrap(); "
                    "use std::io::Write; file.write_all(bytes).unwrap(); std::fs::rename(temporary, target).unwrap(); }\n"
                ) * 50,
                encoding="utf-8",
            )

            score, detail = rust_migration_progress_evidence(root, [manifest])

            self.assertEqual(score, 0.015)
            self.assertIn("atomic writing", detail)

    def test_comments_in_rust_do_not_create_delegation_findings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            candidate = Path(raw) / "candidate"
            package = candidate / "codebase"
            (package / "rust/src").mkdir(parents=True)
            (package / "rust/src/worker_ipc.rs").write_text(
                '// The old implementation was src/Worker.js.\n'
                'pub fn run() {}\n',
                encoding="utf-8",
            )
            self.assertEqual(legacy_engine_paths(candidate), set())

    def test_renamed_copy_of_public_engine_is_quarantined_by_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            public = root / "public"
            candidate = root / "candidate"
            public_engine = public / "src/Worker.js"
            public_engine.parent.mkdir(parents=True)
            public_engine.write_text("module.exports = function legacyWorker() {};\n", encoding="utf-8")
            package = candidate / "codebase"
            renamed = package / "rust/legacy_worker_bridge.js"
            renamed.parent.mkdir(parents=True)
            renamed.write_text(public_engine.read_text(encoding="utf-8"), encoding="utf-8")

            # The verifier normally receives this mount from Docker. The
            # helper accepts the same location through an explicit test env.
            import os

            previous = os.environ.get("ASTRA_PUBLIC_ROOT")
            os.environ["ASTRA_PUBLIC_ROOT"] = str(public)
            try:
                self.assertIn("rust/legacy_worker_bridge.js", legacy_engine_paths(candidate))
                self.assertIn("rust/legacy_worker_bridge.js", legacy_engine_module_patterns(candidate))
                self.assertIn("rust/legacy_worker_bridge.js", retained_legacy_engine_copies(candidate))
            finally:
                if previous is None:
                    os.environ.pop("ASTRA_PUBLIC_ROOT", None)
                else:
                    os.environ["ASTRA_PUBLIC_ROOT"] = previous


if __name__ == "__main__":
    unittest.main()
