import tempfile
import unittest
from pathlib import Path

from verifier.jscodeshift_checks import (
    ALLOWED_JS_BRIDGE_PATHS,
    _remove_non_bridge_sources,
    legacy_engine_module_patterns,
    legacy_engine_paths,
    retained_legacy_engine_copies,
)


class MigrationOwnershipTests(unittest.TestCase):
    def test_bridge_only_cleanup_removes_renamed_implementation_sources(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / "candidate"
            package.mkdir()
            (package / "rust-compat.js").write_text("module.exports = {};\n", encoding="utf-8")
            (package / "lib/renamed-engine.js").parent.mkdir(parents=True)
            (package / "lib/renamed-engine.js").write_text("module.exports = {};\n", encoding="utf-8")
            (package / "src/parser.ts").parent.mkdir(parents=True)
            (package / "src/parser.ts").write_text("export const parser = true;\n", encoding="utf-8")

            removed = _remove_non_bridge_sources(package)

            self.assertEqual(set(removed), {"lib/renamed-engine.js", "src/parser.ts"})
            self.assertTrue((package / "rust-compat.js").is_file())
            self.assertEqual(ALLOWED_JS_BRIDGE_PATHS, {
                "index.js", "bin/jscodeshift.js", "rust-compat.js", "rust-compat-worker.js"
            })

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

            # The verifier normally receives this mount from Docker.  The
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
