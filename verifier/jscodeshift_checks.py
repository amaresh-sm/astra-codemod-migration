"""Private black-box checks for the jscodeshift JavaScript-to-Rust migration."""

from __future__ import annotations

import os
import json
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CRITERIA = (
    "cli-transform-api",
    "parser-and-transform-variants",
    "file-selection-and-stdin",
    "dry-run-print-and-reporting",
    "parallel-workers-and-results",
    "failure-and-exit-contract",
    "cli-surface-and-identity",
    "silent-output-contract",
    "symlink-boundary",
    "parallel-failure-recovery",
    "lifecycle-manifest",
    "custom-option-forwarding",
    "atomic-write-on-error",
    "parallel-result-determinism",
    "utf8-source-preservation",
    "ast-collections-and-builders",
    "ast-formatting-and-comments",
    "ast-modern-syntax",
    "core-api-surface",
    "collection-extensions",
    "template-code-generation",
    "package-root-export",
    "rust-runner-entrypoint",
    "rust-parser-printer-ownership",
    "rust-core-collections-ownership",
    "rust-worker-execution-ownership",
    "rust-package-api-ownership",
    "cross-feature-compatibility",
    "package-boundary-compatibility",
    "ast-composition-corpus",
    "worker-replay-consistency",
)

SCENARIO_IDS = {
    "cli-transform-api": "jscodeshift.cli-transform-api",
    "parser-and-transform-variants": "jscodeshift.parser-and-transform-variants",
    "file-selection-and-stdin": "jscodeshift.file-selection-and-stdin",
    "dry-run-print-and-reporting": "jscodeshift.dry-run-print-and-reporting",
    "parallel-workers-and-results": "jscodeshift.parallel-workers-and-results",
    "failure-and-exit-contract": "jscodeshift.failure-and-exit-contract",
    "cli-surface-and-identity": "jscodeshift.cli-surface-and-identity",
    "silent-output-contract": "jscodeshift.silent-output-contract",
    "symlink-boundary": "jscodeshift.symlink-boundary",
    "parallel-failure-recovery": "jscodeshift.parallel-failure-recovery",
    "lifecycle-manifest": "jscodeshift.lifecycle-manifest",
    "custom-option-forwarding": "jscodeshift.custom-option-forwarding",
    "atomic-write-on-error": "jscodeshift.atomic-write-on-error",
    "parallel-result-determinism": "jscodeshift.parallel-result-determinism",
    "utf8-source-preservation": "jscodeshift.utf8-source-preservation",
    "ast-collections-and-builders": "jscodeshift.ast-collections-and-builders",
    "ast-formatting-and-comments": "jscodeshift.ast-formatting-and-comments",
    "ast-modern-syntax": "jscodeshift.ast-modern-syntax",
    "core-api-surface": "jscodeshift.core-api-surface",
    "collection-extensions": "jscodeshift.collection-extensions",
    "template-code-generation": "jscodeshift.template-code-generation",
    "package-root-export": "jscodeshift.package-root-export",
    "rust-runner-entrypoint": "jscodeshift.rust-runner-entrypoint",
    "rust-parser-printer-ownership": "jscodeshift.rust-parser-printer-ownership",
    "rust-core-collections-ownership": "jscodeshift.rust-core-collections-ownership",
    "rust-worker-execution-ownership": "jscodeshift.rust-worker-execution-ownership",
    "rust-package-api-ownership": "jscodeshift.rust-package-api-ownership",
    "cross-feature-compatibility": "jscodeshift.cross-feature-compatibility",
    "package-boundary-compatibility": "jscodeshift.package-boundary-compatibility",
    "ast-composition-corpus": "jscodeshift.ast-composition-corpus",
    "worker-replay-consistency": "jscodeshift.worker-replay-consistency",
}


def source_root(candidate: Path) -> Path:
    """Resolve the public codebase directory in a candidate workspace."""

    nested = candidate / "codebase"
    return nested if nested.is_dir() else candidate


def runtime_source_root(candidate: Path) -> str:
    """Return the submitted source root as seen by the verifier CLI process.

    Private checks invoke the public CLI from the read-only candidate mount in
    the verifier container.  The separate candidate-runtime container is only
    used for lifecycle commands, so loader guards must target ``/input``.
    """

    return "/input/candidate/codebase" if (candidate / "codebase").is_dir() else "/input/candidate"


def cli_path(candidate: Path) -> Path:
    """Return the stable jscodeshift shell entrypoint."""

    root = source_root(candidate)
    for relative in ("bin/jscodeshift.sh", "bin/jscodeshift.js"):
        path = root / relative
        if path.is_file():
            return path
    raise RuntimeError("candidate does not provide a jscodeshift launcher")


def run_cli(
    candidate: Path,
    args: list[str],
    *,
    cwd: Path,
    stdin: str | None = None,
    timeout: float = 90.0,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the submitted CLI as a black box."""

    return subprocess.run(
        [str(cli_path(candidate)), *args],
        cwd=cwd,
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env={
            **os.environ,
            "NO_COLOR": "1",
            # Expose the submitted package root only to the probe transform.
            # This lets the verifier test the public package export without
            # depending on a particular candidate directory layout.
            "JSCODESHIFT_PACKAGE": str(source_root(candidate)),
            **(extra_env or {}),
        },
    )


def write_transform(path: Path, source: str) -> Path:
    """Write a temporary transform."""

    path.write_text(source, encoding="utf-8")
    return path


def check_cli_transform_api(candidate: Path) -> tuple[bool, str]:
    """Check transform loading, async support, API compatibility, and options."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-api-") as raw:
        root = Path(raw)
        source = root / "source.js"
        source.write_text("const oldName = 1; console.log(oldName);\n", encoding="utf-8")
        transform = write_transform(
            root / "rename.js",
            """
module.exports = function(file, api, options) {
  if (!file.path || typeof api.jscodeshift !== 'function' || typeof api.stats !== 'function') {
    throw new Error('incompatible transform API');
  }
  const root = api.jscodeshift(file.source);
  root.find(api.jscodeshift.Identifier).forEach(path => {
    if (path.node.name === options.from) path.node.name = options.to;
  });
  return root.toSource();
};
""".strip()
            + "\n",
        )
        result = run_cli(
            candidate,
            ["--run-in-band", "--transform", str(transform), "--from", "oldName", "--to", "newName", str(source)],
            cwd=root,
        )
        if result.returncode != 0 or "newName" not in source.read_text(encoding="utf-8"):
            return False, f"JavaScript transform failed (rc={result.returncode})"

        typed = root / "typed.ts"
        typed.write_text("const value: number = 1;\n", encoding="utf-8")
        typed_transform = write_transform(
            root / "typed-transform.ts",
            "module.exports = function(file: any, api: any) { return file.source + '\\n// typed'; };\n",
        )
        typed_result = run_cli(
            candidate,
            ["--run-in-band", "--parser", "ts", "--transform", str(typed_transform), str(typed)],
            cwd=root,
        )
        if typed_result.returncode != 0 or "// typed" not in typed.read_text(encoding="utf-8"):
            return False, f"TypeScript transform failed (rc={typed_result.returncode})"

        async_source = root / "async.js"
        async_source.write_text("const asyncValue = 1;\n", encoding="utf-8")
        async_transform = write_transform(
            root / "async-transform.js",
            """
module.exports = async function(file, api, options) {
  if (options.marker !== 'async-ok' ||
      !Array.isArray(options.tag) || options.tag.join(',') !== 'one,two' ||
      typeof api.jscodeshift !== 'function') {
    throw new Error('async transform options/API mismatch');
  }
  await Promise.resolve();
  return file.source.replace('asyncValue', 'asyncResult');
};
""".strip()
            + "\n",
        )
        async_result = run_cli(
            candidate,
            ["--run-in-band", "--no-babel", "--transform", str(async_transform), "--marker", "async-ok", "--tag=one", "--tag=two", str(async_source)],
            cwd=root,
        )
        if async_result.returncode != 0 or "asyncResult" not in async_source.read_text(encoding="utf-8"):
            return False, f"async transform or custom option failed (rc={async_result.returncode})"

        default_source = root / "default-export.js"
        default_source.write_text("const defaultValue = 1;\n", encoding="utf-8")
        default_transform = write_transform(
            root / "default-transform.ts",
            """
export default function(file: any, api: any) {
  if (api.j !== api.jscodeshift || typeof api.report !== 'function') {
    throw new Error('default export transform API mismatch');
  }
  return file.source + '\\n// default-export-ok';
}
""".strip()
            + "\n",
        )
        default_result = run_cli(
            candidate,
            ["--run-in-band", "--transform", str(default_transform), str(default_source)],
            cwd=root,
        )
        if default_result.returncode != 0 or "// default-export-ok" not in default_source.read_text(encoding="utf-8"):
            return False, f"Babel-transpiled default transform failed (rc={default_result.returncode})"
    return True, "JavaScript, TypeScript, async transforms, and transform options received the expected API"


class _TransformHandler(BaseHTTPRequestHandler):
    """Serve a deterministic transform body for the URL-transform contract."""

    body = b"module.exports = file => file.source + '\\n// url-transform';\n"

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args):
        return


def check_parser_and_transform_variants(candidate: Path) -> tuple[bool, str]:
    """Check TSX/Flow parsers, transform-declared parsers, and URL transforms."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-parsers-") as raw:
        root = Path(raw)
        tsx = root / "component.tsx"
        tsx.write_text("const view = <Button label=\"old\" />;\n", encoding="utf-8")
        tsx_transform = write_transform(
            root / "tsx-transform.js",
            """
module.exports = function(file, api) {
  const root = api.jscodeshift(file.source);
  const attributes = root.find(api.jscodeshift.JSXAttribute);
  if (attributes.size() !== 1) throw new Error('tsx parser did not expose JSX');
  attributes.forEach(path => { path.node.value.value = 'new'; });
  return root.toSource();
};
""".strip()
            + "\n",
        )
        tsx_result = run_cli(
            candidate,
            ["--run-in-band", "--parser", "tsx", "--transform", str(tsx_transform), str(tsx)],
            cwd=root,
        )
        if tsx_result.returncode != 0 or 'label="new"' not in tsx.read_text(encoding="utf-8"):
            return False, f"TSX parser/AST transform failed (rc={tsx_result.returncode})"

        flow = root / "flow.js"
        flow.write_text("// @flow\nfunction greet(name: string): string { return name; }\n", encoding="utf-8")
        flow_transform = write_transform(
            root / "flow-transform.js",
            "module.exports = (file, api) => api.jscodeshift(file.source).toSource() + '\\n// flow-ok';\n",
        )
        flow_result = run_cli(
            candidate,
            ["--run-in-band", "--parser", "flow", "--transform", str(flow_transform), str(flow)],
            cwd=root,
        )
        if flow_result.returncode != 0 or "// flow-ok" not in flow.read_text(encoding="utf-8"):
            return False, f"Flow parser failed (rc={flow_result.returncode})"

        configured_source = root / "configured.js"
        configured_source.write_text("const fragment = <Card />;\n", encoding="utf-8")
        parser_config = root / "parser-config.json"
        parser_config.write_text('{"sourceType":"module","plugins":["jsx"]}\n', encoding="utf-8")
        configured_transform = write_transform(
            root / "configured-transform.js",
            "module.exports = (file, api) => api.jscodeshift(file.source).find(api.jscodeshift.JSXElement).size() === 1 ? file.source + '\\n// config-ok' : null;\n",
        )
        configured_result = run_cli(
            candidate,
            ["--run-in-band", "--parser", "babylon", "--parser-config", str(parser_config), "--transform", str(configured_transform), str(configured_source)],
            cwd=root,
        )
        if configured_result.returncode != 0 or "// config-ok" not in configured_source.read_text(encoding="utf-8"):
            return False, f"custom parser configuration failed (rc={configured_result.returncode})"

        declared = root / "declared.tsx"
        declared.write_text("const panel = <Panel />;\n", encoding="utf-8")
        declared_transform = write_transform(
            root / "declared-parser.js",
            """
module.exports = function(file, api) {
  const root = api.jscodeshift(file.source);
  if (root.find(api.jscodeshift.JSXElement).size() !== 1) throw new Error('declared parser failed');
  return file.source + '\\n// declared-parser-ok';
};
module.exports.parser = 'tsx';
""".strip()
            + "\n",
        )
        declared_result = run_cli(
            candidate,
            ["--run-in-band", "--transform", str(declared_transform), str(declared)],
            cwd=root,
        )
        if declared_result.returncode != 0 or "// declared-parser-ok" not in declared.read_text(encoding="utf-8"):
            return False, f"transform-declared parser failed (rc={declared_result.returncode})"

        server = ThreadingHTTPServer(("127.0.0.1", 0), _TransformHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            remote = root / "remote.js"
            remote.write_text("const remote = true;\n", encoding="utf-8")
            url = f"http://127.0.0.1:{server.server_port}/transform.js"
            remote_result = run_cli(candidate, ["--run-in-band", "--transform", url, str(remote)], cwd=root)
            if remote_result.returncode != 0 or "// url-transform" not in remote.read_text(encoding="utf-8"):
                return False, f"URL transform failed (rc={remote_result.returncode})"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    return True, "TSX, Flow, transform-declared parser, and local URL transforms behaved correctly"


def check_file_selection_and_stdin(candidate: Path) -> tuple[bool, str]:
    """Check recursive selection, extension filtering, ignores, and stdin paths."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-selection-") as raw:
        raw_root = Path(raw)
        root = raw_root / "project"
        root.mkdir()
        nested = root / "nested"
        nested.mkdir()
        for name in ("keep.js", "skip.js", "config-ignored.js", "git-ignored.js"):
            (root / name).write_text(name + "\n", encoding="utf-8")
        (nested / "nested.js").write_text("nested\n", encoding="utf-8")
        (root / "typed.ts").write_text("typed\n", encoding="utf-8")
        (root / "notes.txt").write_text("notes\n", encoding="utf-8")
        # --gitignore reads the file in the process working directory, not
        # one discovered inside the PATH directory.
        (raw_root / ".gitignore").write_text("project/git-ignored.js\n", encoding="utf-8")
        ignore_config = raw_root / "ignore.config"
        ignore_config.write_text("config-ignored.js\n", encoding="utf-8")
        # Keep the transform outside PATH; the historical runner treats files
        # under PATH as inputs when a directory is supplied.
        transform = write_transform(raw_root / "touch.js", "module.exports = file => '// touched\\n' + file.source;\n")
        result = run_cli(
            candidate,
            ["--run-in-band", "--extensions", "js", "--ignore-pattern", "skip.js", "--transform", str(transform), "project"],
            cwd=raw_root,
        )
        if result.returncode != 0:
            return False, f"recursive selection failed (rc={result.returncode})"
        if "// touched" not in (root / "keep.js").read_text() or "// touched" not in (nested / "nested.js").read_text():
            return False, "expected JavaScript files were not selected"
        if any("// touched" in (root / name).read_text() for name in ("skip.js", "typed.ts", "notes.txt")):
            return False, "extension or ignore filtering selected an excluded file"

        # The first run intentionally exercises --ignore-pattern only. Reset
        # the files used by the following independent ignore-source checks so
        # their assertions do not depend on an earlier mutation.
        (root / "config-ignored.js").write_text("config-ignored.js\n", encoding="utf-8")
        (root / "git-ignored.js").write_text("git-ignored.js\n", encoding="utf-8")

        configured = run_cli(
            candidate,
            ["--run-in-band", "--extensions", "js", "--ignore-config", str(ignore_config), "--transform", str(transform), "project"],
            cwd=raw_root,
        )
        if configured.returncode != 0 or "// touched" in (root / "config-ignored.js").read_text(encoding="utf-8"):
            return False, "ignore-config did not exclude the configured file"

        (root / "git-ignored.js").write_text("git-ignored.js\n", encoding="utf-8")

        gitignored = run_cli(
            candidate,
            ["--run-in-band", "--extensions", "js", "--gitignore", "--transform", str(transform), "project"],
            cwd=raw_root,
        )
        if gitignored.returncode != 0 or "// touched" in (root / "git-ignored.js").read_text(encoding="utf-8"):
            return False, "--gitignore did not exclude the .gitignore match"

        stdin_result = run_cli(
            candidate,
            ["--run-in-band", "--stdin", "--transform", str(transform)],
            cwd=raw_root,
            stdin=f"{root / 'keep.js'}\n{root / 'nested/nested.js'}\n\n",
        )
        if stdin_result.returncode != 0:
            return False, f"stdin selection failed (rc={stdin_result.returncode})"
    return True, "recursive, extension, ignore, and stdin selection behaved correctly"


def check_dry_print_reporting(candidate: Path) -> tuple[bool, str]:
    """Check dry-run immutability, print output, statistics, and reports."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-dry-") as raw:
        root = Path(raw)
        source = root / "source.js"
        original = "const value = 1;\n"
        source.write_text(original, encoding="utf-8")
        transform = write_transform(
            root / "observe.js",
            """
module.exports = function(file, api) {
  api.stats('visited');
  api.report('audit-ok');
  return file.source + '\\n// changed';
};
""".strip()
            + "\n",
        )
        result = run_cli(
            candidate,
            ["--run-in-band", "--dry", "--print", "--transform", str(transform), str(source)],
            cwd=root,
        )
        if result.returncode != 0:
            return False, f"dry run failed (rc={result.returncode})"
        if source.read_text(encoding="utf-8") != original:
            return False, "dry run modified the source file"
        missing = [item for item in ("// changed", "Stats:", "visited: 1", "audit-ok") if item not in result.stdout]
        if missing:
            return False, "missing output: " + ", ".join(missing)

        nochange = root / "nochange.js"
        nochange.write_text("const same = true;\n", encoding="utf-8")
        nochange_transform = write_transform(root / "nochange-transform.js", "module.exports = file => file.source;\n")
        nochange_result = run_cli(
            candidate,
            ["--run-in-band", "--verbose", "1", "--transform", str(nochange_transform), str(nochange)],
            cwd=root,
        )
        if nochange_result.returncode != 0 or "NOC" not in nochange_result.stdout:
            return False, "unchanged transform was not reported as nochange"

        skipped = root / "skipped.js"
        skipped.write_text("const skipped = true;\n", encoding="utf-8")
        skip_transform = write_transform(root / "skip-transform.js", "module.exports = () => null;\n")
        skip_result = run_cli(
            candidate,
            ["--run-in-band", "--verbose", "1", "--transform", str(skip_transform), str(skipped)],
            cwd=root,
        )
        if skip_result.returncode != 0 or "SKIP" not in skip_result.stdout:
            return False, "null transform was not reported as skip"
    return True, "dry run, print output, statistics, reports, and result statuses were preserved"


def check_parallel_workers(candidate: Path) -> tuple[bool, str]:
    """Check CPU limits, each-file processing, status aggregation, and serial mode."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-workers-") as raw:
        raw_root = Path(raw)
        root = raw_root / "project"
        root.mkdir()
        for index in range(4):
            (root / f"file-{index}.js").write_text(f"const n = {index};\n", encoding="utf-8")
        transform = write_transform(
            raw_root / "worker.js",
            """
module.exports = file => {
  if (file.path.endsWith('file-0.js')) return null;
  if (file.path.endsWith('file-1.js')) return file.source;
  return file.source + '// worker\\n';
};
""".strip()
            + "\n",
        )
        result = run_cli(candidate, ["--cpus", "2", "--transform", str(transform), "project"], cwd=raw_root)
        if result.returncode != 0:
            return False, f"parallel run failed (rc={result.returncode})"
        changed = sum("// worker" in (root / f"file-{index}.js").read_text() for index in (2, 3))
        if changed != 2:
            return False, f"only {changed}/2 changed files were transformed"
        if "// worker" in (root / "file-0.js").read_text() or "// worker" in (root / "file-1.js").read_text():
            return False, "nochange/skip transforms were incorrectly written"
        if "Processing 4 files" not in result.stdout or "Spawning 2 workers" not in result.stdout:
            return False, "worker summary did not report the requested worker count"
        if "1 unmodified" not in result.stdout or "1 skipped" not in result.stdout or "2 ok" not in result.stdout:
            return False, "worker summary did not aggregate per-file statuses"

        serial_root = root / "serial"
        serial_root.mkdir()
        for index in range(3):
            (serial_root / f"serial-{index}.js").write_text("const serial = true;\n", encoding="utf-8")
        serial = run_cli(
            candidate,
            ["--run-in-band", "--verbose", "2", "--transform", str(transform), str(serial_root)],
            cwd=root,
        )
        if serial.returncode != 0 or "Spawning" in serial.stdout or "Processing 3 files" not in serial.stdout:
            return False, "--run-in-band did not use the serial execution contract"
        if serial.stdout.count("OK") != 3:
            return False, "serial mode did not report every successful file"
    return True, "parallel and serial workers processed every file with correct aggregate statuses"


def check_failure_contract(candidate: Path) -> tuple[bool, str]:
    """Check per-file errors, strict exit behavior, and CLI validation errors."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-errors-") as raw:
        root = Path(raw)
        source = root / "source.js"
        source.write_text("const value = 1;\n", encoding="utf-8")
        transform = write_transform(root / "fail.js", "module.exports = function() { throw new Error('boom'); };\n")
        normal = run_cli(candidate, ["--run-in-band", "--transform", str(transform), str(source)], cwd=root)
        if normal.returncode != 0 or "ERR" not in normal.stdout or "boom" not in normal.stdout:
            return False, "ordinary transform failure did not produce the expected error result"

        good = root / "good.js"
        bad = root / "bad.js"
        good.write_text("const good = true;\n", encoding="utf-8")
        bad.write_text("const bad = true;\n", encoding="utf-8")
        mixed_transform = write_transform(
            root / "mixed-failure.js",
            """
module.exports = function(file) {
  if (file.path.endsWith('bad.js')) throw new Error('bad-file');
  return file.source + '\\n// good-file';
};
""".strip()
            + "\n",
        )
        mixed = run_cli(
            candidate,
            ["--run-in-band", "--transform", str(mixed_transform), str(good), str(bad)],
            cwd=root,
        )
        if mixed.returncode != 0 or "good-file" not in good.read_text(encoding="utf-8") or "bad-file" not in mixed.stdout:
            return False, "one file failure prevented the other files from completing"

        strict = run_cli(candidate, ["--run-in-band", "--fail-on-error", "--transform", str(transform), str(source)], cwd=root)
        if strict.returncode == 0:
            return False, "--fail-on-error did not return non-zero"

        invalid_parser = run_cli(
            candidate,
            ["--parser", "not-a-parser", "--transform", str(transform), str(source)],
            cwd=root,
        )
        if invalid_parser.returncode == 0 or "parser" not in (invalid_parser.stdout + invalid_parser.stderr).lower():
            return False, "invalid parser was not rejected"

        missing_value = run_cli(candidate, ["--transform"], cwd=root)
        if missing_value.returncode == 0 or "requires a value" not in (missing_value.stdout + missing_value.stderr):
            return False, "missing option value was not rejected"

        missing_path = run_cli(
            candidate,
            ["--run-in-band", "--transform", str(transform), str(root / "does-not-exist.js")],
            cwd=root,
        )
        if missing_path.returncode != 0 or "does-not-exist.js" not in (missing_path.stdout + missing_path.stderr):
            return False, "missing input path did not produce the documented diagnostic"
    return True, "transform errors and --fail-on-error behaved correctly"


def check_cli_surface_and_identity(candidate: Path) -> tuple[bool, str]:
    """Check help/version discoverability and documented short-option behavior."""

    help_result = run_cli(candidate, ["--help"], cwd=source_root(candidate))
    help_text = help_result.stdout + help_result.stderr
    required = ("--transform", "--extensions", "--stdin", "--run-in-band", "--fail-on-error")
    if help_result.returncode != 0 or any(option not in help_text for option in required):
        return False, "help output does not expose the required CLI surface"
    version = run_cli(candidate, ["--version"], cwd=source_root(candidate))
    if version.returncode != 0 or "jscodeshift:" not in version.stdout:
        return False, "--version did not return the jscodeshift version"
    with tempfile.TemporaryDirectory(prefix="jscodeshift-cli-surface-") as raw:
        root = Path(raw)
        source = root / "short.js"
        source.write_text("const short = true;\n", encoding="utf-8")
        transform = write_transform(root / "short-transform.js", "module.exports = file => file.source + '\\n// short-ok';\n")
        result = run_cli(candidate, ["-t", str(transform), "-c", "1", str(source)], cwd=root)
        if result.returncode != 0 or "// short-ok" not in source.read_text(encoding="utf-8"):
            return False, "documented short CLI options did not execute a transform"
    return True, "help, version, and documented short options remain compatible"


def check_silent_output_contract(candidate: Path) -> tuple[bool, str]:
    """Check that --silent suppresses all CLI output while still writing changes."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-silent-") as raw:
        root = Path(raw)
        source = root / "silent.js"
        source.write_text("const silent = true;\n", encoding="utf-8")
        transform = write_transform(root / "silent-transform.js", "module.exports = file => file.source + '\\n// silent-ok';\n")
        result = run_cli(candidate, ["--run-in-band", "--silent", "--transform", str(transform), str(source)], cwd=root)
        if result.returncode != 0 or result.stdout or result.stderr:
            return False, "--silent did not suppress CLI output"
        if "// silent-ok" not in source.read_text(encoding="utf-8"):
            return False, "--silent did not write the transformed source"
    return True, "--silent suppresses output without suppressing the transform"


def check_symlink_boundary(candidate: Path) -> tuple[bool, str]:
    """Check that file discovery preserves legacy symlink traversal semantics."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-links-") as raw, tempfile.TemporaryDirectory(prefix="jscodeshift-outside-") as outside_raw:
        root = Path(raw) / "project"
        outside = Path(outside_raw)
        root.mkdir()
        (root / "z.js").write_text("z\n", encoding="utf-8")
        (root / "a.js").write_text("a\n", encoding="utf-8")
        (root / "inside-link.js").symlink_to(root / "a.js")
        (outside / "secret.js").write_text("secret\n", encoding="utf-8")
        (root / "outside-link.js").symlink_to(outside / "secret.js")
        transform = write_transform(Path(raw) / "touch.js", "module.exports = file => file.source + '\\n// link-ok';\n")
        result = run_cli(candidate, ["--run-in-band", "--extensions", "js", "--transform", str(transform), "project"], cwd=Path(raw))
        if result.returncode != 0:
            return False, f"symlink selection failed (rc={result.returncode})"
        if "// link-ok" not in (root / "a.js").read_text(encoding="utf-8"):
            return False, "safe in-root symlink target was not processed"
        if "// link-ok" not in (outside / "secret.js").read_text(encoding="utf-8"):
            return False, "out-of-root symlink was not processed as it is by the legacy runner"
    return True, "symlink discovery preserves legacy in-root and out-of-root link processing"


def check_parallel_failure_recovery(candidate: Path) -> tuple[bool, str]:
    """Check that one worker failure does not prevent independent files completing."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-worker-errors-") as raw:
        root = Path(raw)
        project = root / "project"
        project.mkdir()
        good = project / "good.js"
        bad = project / "bad.js"
        good.write_text("const good = true;\n", encoding="utf-8")
        bad.write_text("const bad = true;\n", encoding="utf-8")
        transform = write_transform(
            root / "worker-error.js",
            """
module.exports = function(file) {
  if (file.path.endsWith('bad.js')) throw new Error('worker-boom');
  return file.source + '\\n// worker-good';
};
""".strip()
            + "\n",
        )
        result = run_cli(candidate, ["--cpus", "2", "--transform", str(transform), "project"], cwd=root)
        if result.returncode != 0:
            return False, f"parallel failure recovery returned rc={result.returncode}"
        if "// worker-good" not in good.read_text(encoding="utf-8"):
            return False, "successful worker result was lost after a peer failure"
        if "worker-boom" not in result.stdout:
            return False, "worker failure was not reported"
        if "1 error" not in result.stdout and "1 errors" not in result.stdout:
            return False, "parallel aggregate did not count the failed worker"
    return True, "parallel workers isolate failures and complete independent files"


def check_lifecycle_manifest(candidate: Path) -> tuple[bool, str]:
    """Check the candidate lifecycle handoff without imposing implementation details."""

    import json

    manifest = candidate / "app-setup" / "manifest.json"
    if not manifest.is_file():
        return False, "app-setup/manifest.json is missing"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"manifest is not valid JSON: {exc}"
    commands = payload.get("commands") if isinstance(payload, dict) else None
    if not isinstance(commands, dict):
        return False, "manifest has no commands object"
    for name in ("build", "reset", "start"):
        command = commands.get(name)
        if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
            return False, f"manifest command {name!r} is not a non-empty argument array"
        executable = candidate / command[-1] if len(command) >= 2 else None
        if executable is None or not executable.is_file():
            return False, f"manifest command {name!r} points to a missing script"
    return True, "build, reset, and start lifecycle commands are declared"


def check_custom_option_forwarding(candidate: Path) -> tuple[bool, str]:
    """Check repeatable and equals-form custom options reaching JavaScript transforms."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-options-") as raw:
        root = Path(raw)
        source = root / "options.js"
        source.write_text("const options = true;\n", encoding="utf-8")
        transform = write_transform(
            root / "options-transform.js",
            """
module.exports = function(file, api, options) {
  if (options.marker !== 'equals-ok' || !Array.isArray(options.tag) || options.tag.join(',') !== 'one,two') {
    throw new Error('custom options were not forwarded');
  }
  return file.source + '\\n// options-ok';
};
""".strip()
            + "\n",
        )
        result = run_cli(
            candidate,
            ["--run-in-band", "--transform", str(transform), "--marker=equals-ok", "--tag=one", "--tag", "two", str(source)],
            cwd=root,
        )
        if result.returncode != 0 or "// options-ok" not in source.read_text(encoding="utf-8"):
            return False, "custom option values were not preserved"
    return True, "repeatable and equals-form custom options reach transforms"


def check_atomic_write_on_error(candidate: Path) -> tuple[bool, str]:
    """Check that a failed transform cannot partially overwrite its source."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-atomic-") as raw:
        root = Path(raw)
        source = root / "atomic.js"
        original = "const keep = true;\n"
        source.write_text(original, encoding="utf-8")
        transform = write_transform(
            root / "throw-after-change.js",
            """
module.exports = function(file) {
  const changed = file.source + '\\n// should-not-write';
  if (changed) throw new Error('atomic-boom');
  return changed;
};
""".strip()
            + "\n",
        )
        result = run_cli(candidate, ["--run-in-band", "--transform", str(transform), str(source)], cwd=root)
        if result.returncode != 0 or "atomic-boom" not in (result.stdout + result.stderr):
            return False, "transform failure was not reported"
        if source.read_text(encoding="utf-8") != original:
            return False, "failed transform partially overwrote its source"
    return True, "failed transforms leave source files unchanged"


def check_parallel_result_determinism(candidate: Path) -> tuple[bool, str]:
    """Check that parallel scheduling preserves stable aggregate result counts."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-determinism-") as raw:
        root = Path(raw)
        project = root / "project"
        project.mkdir()
        for index in range(6):
            (project / f"file-{index}.js").write_text(f"const n = {index};\n", encoding="utf-8")
        transform = write_transform(root / "stable.js", "module.exports = file => file.source + '\\n// stable';\n")
        outputs: list[str] = []
        for _ in range(2):
            for index in range(6):
                (project / f"file-{index}.js").write_text(f"const n = {index};\n", encoding="utf-8")
            result = run_cli(candidate, ["--cpus", "3", "--transform", str(transform), "project"], cwd=root)
            if result.returncode != 0:
                return False, f"parallel run failed (rc={result.returncode})"
            if "Processing 6 files" not in result.stdout or "6 ok" not in result.stdout:
                return False, "parallel aggregate counts were incomplete"
            outputs.append("\n".join(line for line in result.stdout.splitlines() if line.startswith(("Processing", "Spawning", "Results:"))))
        if outputs[0] != outputs[1]:
            return False, "parallel aggregate reporting changed with scheduling"
    return True, "parallel scheduling produces stable aggregate results"


def check_utf8_source_preservation(candidate: Path) -> tuple[bool, str]:
    """Check that a no-op transform preserves UTF-8 source bytes and line content."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-utf8-") as raw:
        root = Path(raw)
        source = root / "unicode.js"
        original = "const café = '東京 🚀';\n// naïve façade\n"
        source.write_text(original, encoding="utf-8")
        transform = write_transform(root / "noop.js", "module.exports = file => file.source;\n")
        result = run_cli(candidate, ["--run-in-band", "--transform", str(transform), str(source)], cwd=root)
        if result.returncode != 0 or source.read_text(encoding="utf-8") != original:
            return False, "no-op transform changed UTF-8 source content"
    return True, "UTF-8 source content is preserved for no-op transforms"


def check_ast_collections_and_builders(candidate: Path) -> tuple[bool, str]:
    """Check collection traversal, node replacement, and builder availability."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-ast-builders-") as raw:
        root = Path(raw)
        source = root / "builders.js"
        source.write_text("const oldName = 1;\n", encoding="utf-8")
        transform = write_transform(
            root / "builders-transform.js",
            """
module.exports = function(file, api) {
  const j = api.jscodeshift;
  const ast = j(file.source);
  if (ast.find(j.Identifier, { name: 'oldName' }).size() !== 1) throw new Error('collection traversal failed');
  ast.find(j.Identifier, { name: 'oldName' }).replaceWith(() => j.identifier('newName'));
  return ast.toSource();
};
""".strip()
            + "\n",
        )
        result = run_cli(candidate, ["--run-in-band", "--transform", str(transform), str(source)], cwd=root)
        if result.returncode != 0 or "newName" not in source.read_text(encoding="utf-8") or "oldName" in source.read_text(encoding="utf-8"):
            return False, "collection traversal or standard builders failed"
    return True, "collections and standard AST builders remain available"


def check_ast_formatting_and_comments(candidate: Path) -> tuple[bool, str]:
    """Check that AST edits retain leading comments and stable source formatting."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-ast-format-") as raw:
        root = Path(raw)
        source = root / "comments.js"
        source.write_text("// preserve this comment\nconst value = \"old\";\n", encoding="utf-8")
        transform = write_transform(
            root / "format-transform.js",
            """
module.exports = function(file, api) {
  const j = api.jscodeshift;
  const ast = j(file.source);
  ast.find(j.Literal, { value: 'old' }).forEach(path => { path.node.value = 'new'; });
  return ast.toSource({ quote: 'double' });
};
""".strip()
            + "\n",
        )
        result = run_cli(candidate, ["--run-in-band", "--transform", str(transform), str(source)], cwd=root)
        text = source.read_text(encoding="utf-8")
        if result.returncode != 0 or "// preserve this comment" not in text or '"new"' not in text:
            return False, "AST printing did not preserve comments or requested formatting"
    return True, "AST edits preserve comments and formatting options"


def check_ast_modern_syntax(candidate: Path) -> tuple[bool, str]:
    """Check AST traversal over TypeScript types, TSX, and modern JavaScript syntax."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-ast-syntax-") as raw:
        root = Path(raw)
        source = root / "modern.tsx"
        source.write_text(
            "interface User { name: string }\nconst view = <Card user={user?.name ?? 'unknown'} />;\n",
            encoding="utf-8",
        )
        transform = write_transform(
            root / "modern-transform.js",
            """
module.exports = function(file, api) {
  const j = api.jscodeshift;
  const ast = j(file.source);
  if (ast.find(j.TSInterfaceDeclaration).size() !== 1) throw new Error('TypeScript interface unavailable');
  if (ast.find(j.JSXElement).size() !== 1) throw new Error('TSX element unavailable');
  return file.source + '\\n// modern-syntax-ok';
};
""".strip()
            + "\n",
        )
        result = run_cli(candidate, ["--run-in-band", "--parser", "tsx", "--transform", str(transform), str(source)], cwd=root)
        if result.returncode != 0 or "// modern-syntax-ok" not in source.read_text(encoding="utf-8"):
            return False, "TypeScript/TSX modern syntax was not available to the transform"
    return True, "TypeScript, TSX, and modern JavaScript syntax remain traversable"


def check_core_api_surface(candidate: Path) -> tuple[bool, str]:
    """Exercise the enriched package API, parser binding, matching, and plugins."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-core-api-") as raw:
        root = Path(raw)
        source = root / "core.js"
        source.write_text("const count = 1;\n", encoding="utf-8")
        transform = write_transform(
            root / "core-api-transform.js",
            r'''
module.exports = function(file, api) {
  const j = api.jscodeshift;
  if (api.j !== j) throw new Error('j alias is not the jscodeshift API');
  const exported = require(process.env.JSCODESHIFT_PACKAGE);
  const required = ['withParser', 'use', 'registerMethods', 'template', 'match', 'types'];
  if (typeof exported !== 'function' || required.some(name => typeof exported[name] === 'undefined')) {
    throw new Error('incomplete package core API');
  }
  const typed = exported.withParser('tsx')('const view = <Widget />;\n');
  if (typed.find(exported.JSXElement).size() !== 1) throw new Error('withParser failed');
  // The public core entry point accepts source strings, nodes, node paths,
  // and arrays of either. These forms are used by transforms that compose
  // collections rather than reparsing source text.
  const parsed = exported('const first = 1; const second = 2;');
  const firstNode = parsed.find(exported.VariableDeclarator, {id: {name: 'first'}}).nodes()[0];
  const firstPath = parsed.find(exported.VariableDeclarator, {id: {name: 'first'}}).paths()[0];
  if (exported(firstNode).size() !== 1 || exported([firstNode]).size() !== 1 ||
      exported(firstPath).size() !== 1) throw new Error('core AST input forms failed');
  const identifiers = j(file.source).find(j.Identifier, {name: 'count'});
  if (identifiers.size() !== 1 || !j.match(identifiers.nodes()[0], {type: 'Identifier', name: 'count'})) {
    throw new Error('match or collection API failed');
  }
  const plugin = core => core.registerMethods({markCoreProbe: function() { return this; }});
  j.use(plugin);
  const ast = j(file.source);
  if (ast.markCoreProbe() !== ast) throw new Error('plugin registration failed');
  const statement = j.template.statement`const ${j.identifier('generated')} = ${j.literal(7)};`;
  if (statement.type !== 'VariableDeclaration') throw new Error('template API failed');
  ast.find(j.Program).get('body').value.push(statement);
  return ast.toSource();
};
'''.strip()
            + "\n",
        )
        result = run_cli(candidate, ["--run-in-band", "--transform", str(transform), str(source)], cwd=root)
        text = source.read_text(encoding="utf-8")
        if result.returncode != 0 or "generated" not in text:
            return False, f"core package API compatibility failed (rc={result.returncode})"
    return True, "package core exports, parser binding, matching, plugins, and templates remain compatible"


def check_collection_extensions(candidate: Path) -> tuple[bool, str]:
    """Exercise typed collection methods, filters, mappings, and path accessors."""

    source = "\n".join(
        (
            'import { value } from "pkg";',
            'var Widget = require("ui");',
            'var target = 1;',
            'var view = <Widget label="old"><span>child</span></Widget>;'
        )
    )
    program = (
        "const Collection=require('./src/Collection');"
        "require('./src/collections/ImportDeclaration').register();"
        "require('./src/collections/VariableDeclarator').register();"
        "require('./src/collections/JSXElement').register();"
        "const recast=require('recast');"
        "const getParser=require('./src/getParser');"
        f"const source={source!r};"
        "const ast=recast.parse(source,{parser:getParser()}).program;"
        "const tree=Collection.fromNodes([ast]);"
        "if(!tree.hasImportDeclaration('pkg'))process.exit(2);"
        "tree.renameImportDeclaration('pkg','renamed-pkg');"
        "if(tree.findImportDeclarations('renamed-pkg').size()!==1)process.exit(3);"
        "const vars=tree.findVariableDeclarators('target');"
        "if(vars.size()!==1||vars.at(0).size()!==1||vars.get('id').value.name!=='target'||"
        "vars.filter(p=>p.value.id.name==='target').size()!==1||vars.map(p=>p).size()!==1||vars.paths().length!==1)process.exit(4);"
        "if(!vars.some(p=>p.value.id.name==='target')||!vars.every(p=>p.value.id.name==='target')||"
        "vars.at(-1).size()!==1||!vars.isOfType('VariableDeclarator')||"
        "vars.getTypes().indexOf('VariableDeclarator')===-1)process.exit(7);"
        "vars.renameTo('renamedTarget');"
        "const widgets=tree.findJSXElements('Widget');"
        "const matching=widgets.filter(require('./src/collections/JSXElement').filters.hasAttributes({label:'old'}));"
        "if(matching.size()!==1||matching.childElements().size()!==1||matching.childNodes().size()!==1||"
        "tree.findJSXElementsByModuleName('ui').size()!==1)process.exit(5);"
        "matching.forEach(p=>{p.node.openingElement.attributes[0].value.value='new';});"
        "const output=recast.print(ast).code;"
        "if(!output.includes('renamed-pkg')||!output.includes('renamedTarget')||!output.includes('label=\"new\"'))process.exit(6);"
        "process.stdout.write('ok\\n');"
    )
    result = subprocess.run(
        ["node", "-e", program],
        cwd=source_root(candidate),
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    if result.returncode != 0 or result.stdout.strip() != "ok":
        detail = (result.stdout + "\n" + result.stderr).strip().replace("\n", " ")
        return False, f"typed collection compatibility failed (rc={result.returncode}; {detail[-360:]})"
    return True, "typed collections, filters, mappings, mutations, and path accessors remain compatible"


def check_template_code_generation(candidate: Path) -> tuple[bool, str]:
    """Check statement, expression, and async-expression template helpers."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-templates-") as raw:
        root = Path(raw)
        source = root / "templates.js"
        source.write_text("const existing = 1;\n", encoding="utf-8")
        transform = write_transform(
            root / "templates-transform.js",
            r'''
module.exports = function(file, api) {
  const j = api.jscodeshift;
  const ast = j(file.source);
  const statement = j.template.statement`const ${j.identifier('templated')} = ${j.literal(42)};`;
  const expression = j.template.expression`${j.identifier('templated')} + ${j.literal(1)}`;
  const asyncExpression = j.template.asyncExpression`await ${j.identifier('templated')}`;
  if (statement.type !== 'VariableDeclaration' || expression.type !== 'BinaryExpression' ||
      asyncExpression.type !== 'AwaitExpression') throw new Error('template node types changed');
  const identifiers = [j.identifier('first'), j.identifier('second')];
  const expandedDeclaration = j.template.statement`const ${identifiers} = ${j.literal(1)};`;
  const expandedCall = j.template.expression`invoke(${identifiers})`;
  if (expandedDeclaration.type !== 'VariableDeclaration' ||
      expandedDeclaration.declarations.length !== 2 ||
      expandedCall.type !== 'CallExpression' || expandedCall.arguments.length !== 2) {
    throw new Error('template array interpolation failed');
  }
  ast.find(j.Program).get('body').value.push(statement, j.expressionStatement(expression));
  return ast.toSource();
};
'''.strip()
            + "\n",
        )
        result = run_cli(candidate, ["--run-in-band", "--transform", str(transform), str(source)], cwd=root)
        text = source.read_text(encoding="utf-8")
        if result.returncode != 0 or "templated" not in text or "42" not in text:
            return False, f"template code generation failed (rc={result.returncode})"
    return True, "statement, expression, and async-expression templates retain their public behavior"


def check_cross_feature_compatibility(candidate: Path) -> tuple[bool, str]:
    """Check a realistic CLI/worker/parser/options combination in one run."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-cross-feature-") as raw:
        root = Path(raw)
        project = root / "project"
        project.mkdir()
        source = project / "component.tsx"
        ignored = project / "ignored.tsx"
        source.write_text(
            "// preserve integration comment\n"
            "interface Props { label: string }\n"
            "const view = <Button label=\"old\" />;\n",
            encoding="utf-8",
        )
        ignored.write_text("const ignored = <Button label=\"old\" />;\n", encoding="utf-8")
        transform = write_transform(
            root / "integrated-transform.js",
            r'''
module.exports = function(file, api, options) {
  if (options.mode !== 'integration' || !Array.isArray(options.tag) ||
      options.tag.join(',') !== 'one,two') {
    throw new Error('integration options were not preserved');
  }
  const j = api.jscodeshift;
  const ast = j(file.source);
  if (ast.find(j.TSInterfaceDeclaration).size() !== 1 ||
      ast.find(j.JSXElement).size() !== 1) {
    throw new Error('integration parser did not expose TSX nodes');
  }
  ast.find(j.JSXAttribute).forEach(path => {
    if (path.node.name.name === 'label') path.node.value.value = 'new';
  });
  const marker = j.template.statement`const ${j.identifier('integrated')} = ${j.literal(1)};`;
  ast.find(j.Program).get('body').value.push(marker);
  return ast.toSource({quote: 'double'});
};
module.exports.parser = 'tsx';
'''.strip()
            + "\n",
        )
        result = run_cli(
            candidate,
            [
                "--cpus", "2", "--extensions", "tsx", "--ignore-pattern", "ignored.tsx",
                "--transform", str(transform), "--mode=integration", "--tag=one", "--tag", "two", "project",
            ],
            cwd=root,
        )
        text = source.read_text(encoding="utf-8")
        if result.returncode != 0:
            return False, f"combined CLI/parser/worker run failed (rc={result.returncode})"
        if "label=\"new\"" not in text or "integrated" not in text or "preserve integration comment" not in text:
            return False, "combined transform did not preserve or apply expected changes"
        if "label=\"new\"" in ignored.read_text(encoding="utf-8"):
            return False, "combined run ignored an excluded file incorrectly"
        # A transform-declared parser must still work when the CLI's parser
        # flag is omitted; this is a public jscodeshift behavior rather than
        # an implementation detail of any particular parser. Keep this probe
        # independent from the option-forwarding assertions above so a
        # missing custom option cannot masquerade as parser drift.
        declared = project / "declared.tsx"
        declared.write_text("const view = <Button label=\"old\" />;\n", encoding="utf-8")
        declared_transform = write_transform(
            root / "declared-parser-transform.js",
            r'''
module.exports = function(file, api) {
  const j = api.jscodeshift;
  const ast = j(file.source);
  if (ast.find(j.JSXElement).size() !== 1) throw new Error('declared parser did not expose JSX');
  ast.find(j.JSXAttribute).forEach(path => {
    if (path.node.name.name === 'label') path.node.value.value = 'declared';
  });
  return ast.toSource({quote: 'double'});
};
module.exports.parser = 'tsx';
'''.strip()
            + "\n",
        )
        declared_result = run_cli(
            candidate,
            ["--run-in-band", "--extensions", "tsx", "--transform", str(declared_transform), str(declared)],
            cwd=root,
        )
        if declared_result.returncode != 0 or "label=\"declared\"" not in declared.read_text(encoding="utf-8"):
            return False, "transform-declared parser did not compose with the public CLI"
    return True, "CLI options, worker scheduling, TSX parsing, templates, and ignore rules composed correctly"


def check_package_boundary_compatibility(candidate: Path) -> tuple[bool, str]:
    """Check that npm packaging retains the public entrypoints and export shape."""

    root = source_root(candidate)
    package_json = root / "package.json"
    if not package_json.is_file():
        return False, "package.json is missing"
    with tempfile.TemporaryDirectory(prefix="jscodeshift-package-") as raw:
        work = Path(raw)
        packed = work / "packed"
        packed.mkdir()
        result = subprocess.run(
            ["npm", "pack", "--ignore-scripts", "--json", "--pack-destination", str(packed)],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
        tarballs = sorted(packed.glob("*.tgz"))
        if result.returncode != 0 or len(tarballs) != 1:
            return False, f"npm pack failed (rc={result.returncode})"
        unpacked = work / "unpacked"
        unpacked.mkdir()
        try:
            with tarfile.open(tarballs[0], "r:gz") as archive:
                base = unpacked.resolve()
                for member in archive.getmembers():
                    target = (unpacked / member.name).resolve()
                    if target != base and base not in target.parents:
                        return False, "package archive contains an unsafe path"
                archive.extractall(unpacked)
        except (OSError, tarfile.TarError) as exc:
            return False, f"package archive could not be extracted: {exc}"
        package = unpacked / "package"
        try:
            import json

            payload = json.loads((package / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return False, f"packed package metadata is invalid: {exc}"
        main = payload.get("main", "index.js")
        if not isinstance(main, str) or not (package / main).is_file():
            return False, "packed package main entrypoint is missing"
        bins = payload.get("bin", {})
        if isinstance(bins, str):
            bins = {payload.get("name", "jscodeshift"): bins}
        if not isinstance(bins, dict) or not bins:
            return False, "packed package has no CLI bin entrypoint"
        if any(not isinstance(path, str) or not (package / path).is_file() for path in bins.values()):
            return False, "packed package CLI entrypoint is missing"
        # Exercise the packed bin from outside the source tree. Merely having
        # a path in package.json does not prove that the published launcher is
        # executable or resolves its relative files correctly.
        bin_path = package / next(iter(bins.values()))
        smoke = subprocess.run(
            [str(bin_path), "--version"],
            cwd=work,
            env={**os.environ, "NODE_PATH": str(root / "node_modules"), "NO_COLOR": "1"},
            text=True,
            capture_output=True,
            check=False,
        )
        if smoke.returncode != 0 or "jscodeshift:" not in smoke.stdout:
            return False, "packed CLI entrypoint could not execute outside the source tree"
        probe = (
            "const j=require('./');"
            "if(typeof j!=='function'||typeof j.withParser!=='function'||"
            "typeof j.registerMethods!=='function') process.exit(2);"
            "if(j('const packaged=1;').find(j.Identifier,{name:'packaged'}).size()!==1) process.exit(3);"
        )
        env = {**os.environ, "NODE_PATH": str(root / "node_modules")}
        imported = subprocess.run(["node", "-e", probe], cwd=package, env=env, text=True, capture_output=True, check=False)
        if imported.returncode != 0:
            return False, "packed package root export could not be loaded"
    return True, "npm packaging retains the public package export and CLI entrypoint"


def check_ast_composition_corpus(candidate: Path) -> tuple[bool, str]:
    """Run a private multi-file AST corpus through collections, plugins, and templates."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-ast-corpus-") as raw:
        root = Path(raw)
        project = root / "project"
        project.mkdir()
        (project / "modern.tsx").write_text(
            "// corpus comment\ninterface User { name: string }\n"
            "const view = <Card label=\"old\" user={user?.name ?? 'unknown'} />;\n",
            encoding="utf-8",
        )
        (project / "imports.tsx").write_text(
            "import { value } from 'pkg';\nconst current = value;\nconst view = <Card />;\n",
            encoding="utf-8",
        )
        transform = write_transform(
            root / "corpus-transform.js",
            r'''
module.exports = function(file, api) {
  const j = api.jscodeshift;
  j.use(core => core.registerMethods({ markCorpus() { return this; } }));
  const ast = j(file.source);
  if (ast.markCorpus() !== ast) throw new Error('plugin registration failed');
  if (file.path.endsWith('modern.tsx') &&
      (ast.find(j.TSInterfaceDeclaration).size() !== 1 || ast.find(j.JSXElement).size() !== 1)) {
    throw new Error('modern corpus syntax unavailable');
  }
  if (file.path.endsWith('imports.tsx') && ast.find(j.ImportDeclaration).size() !== 1) {
    throw new Error('import corpus syntax unavailable');
  }
  ast.find(j.JSXAttribute).forEach(path => {
    if (path.node.name.name === 'label') path.node.value.value = 'new';
  });
  const statement = j.template.statement`const ${j.identifier('corpusGenerated')} = ${j.literal(7)};`;
  const expression = j.template.expression`${j.identifier('corpusGenerated')} + ${j.literal(1)}`;
  const asyncExpression = j.template.asyncExpression`await ${j.identifier('corpusGenerated')}`;
  if (statement.type !== 'VariableDeclaration' || expression.type !== 'BinaryExpression' ||
      asyncExpression.type !== 'AwaitExpression') throw new Error('template corpus types changed');
  ast.find(j.Program).get('body').value.push(statement, j.expressionStatement(expression));
  return ast.toSource({quote: 'single'});
};
module.exports.parser = 'tsx';
'''.strip()
            + "\n",
        )
        result = run_cli(candidate, ["--cpus", "2", "--parser", "tsx", "--transform", str(transform), "project"], cwd=root)
        if result.returncode != 0:
            return False, f"AST corpus transform failed (rc={result.returncode})"
        modern = (project / "modern.tsx").read_text(encoding="utf-8")
        imports = (project / "imports.tsx").read_text(encoding="utf-8")
        if "corpusGenerated" not in modern or "corpusGenerated" not in imports:
            return False, "AST corpus templates were not emitted for every file"
        if "corpus comment" not in modern or 'label=\'new\'' not in modern:
            return False, "AST corpus formatting or JSX mutation was not preserved"
    return True, "multi-file AST corpus preserves syntax, plugins, collections, templates, and formatting"


def check_worker_replay_consistency(candidate: Path) -> tuple[bool, str]:
    """Check that delayed and failing worker jobs replay the same file outcomes."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-worker-replay-") as raw:
        root = Path(raw)
        project = root / "project"
        project.mkdir()
        names = ("fast.js", "slow.js", "other.js", "bad.js")
        originals = {}
        for name in names:
            contents = f"const {name[:-3]} = true;\n"
            (project / name).write_text(contents, encoding="utf-8")
            originals[name] = contents
        transform = write_transform(
            root / "replay-transform.js",
            r'''
module.exports = async function(file) {
  const name = file.path.split('/').pop();
  if (name === 'bad.js') throw new Error('replay-boom');
  if (name === 'slow.js') await new Promise(resolve => setTimeout(resolve, 40));
  return file.source + `// replay-${name}\n`;
};
'''.strip()
            + "\n",
        )

        parallel = run_cli(candidate, ["--cpus", "3", "--fail-on-error", "--transform", str(transform), "project"], cwd=root)
        if parallel.returncode == 0 or "replay-boom" not in (parallel.stdout + parallel.stderr):
            return False, "parallel replay did not report the failing worker"
        parallel_changed = {
            name for name in names if "replay-" in (project / name).read_text(encoding="utf-8")
        }
        if parallel_changed != {"fast.js", "slow.js", "other.js"} or (project / "bad.js").read_text(encoding="utf-8") != originals["bad.js"]:
            return False, "parallel replay lost a successful result or wrote a failed file"

        for name, contents in originals.items():
            (project / name).write_text(contents, encoding="utf-8")
        serial = run_cli(candidate, ["--run-in-band", "--fail-on-error", "--transform", str(transform), "project"], cwd=root)
        serial_changed = {
            name for name in names if "replay-" in (project / name).read_text(encoding="utf-8")
        }
        if serial.returncode == 0 or serial_changed != parallel_changed:
            return False, "serial replay did not match parallel file outcomes"
    return True, "parallel and serial worker replays preserve successful, failed, and delayed outcomes"


def check_package_root_export(candidate: Path) -> tuple[bool, str]:
    """Check that the package root still exports the callable jscodeshift API."""

    root = source_root(candidate)
    package_entry = root / "index.js"
    if not package_entry.is_file():
        return False, "package root index.js is missing"
    probe = (
        "const j = require(process.env.JSCODESHIFT_PACKAGE);"
        "if (typeof j !== 'function' || typeof j.withParser !== 'function' || "
        "typeof j.template !== 'object' || typeof j.registerMethods !== 'function') process.exit(2);"
        "const ast = j('const exported = 1;');"
        "if (ast.find(j.Identifier, {name: 'exported'}).size() !== 1) process.exit(3);"
    )
    result = subprocess.run(
        ["node", "-e", probe],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "JSCODESHIFT_PACKAGE": str(root)},
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return False, "package root export failed" + (f": {detail[-1]}" if detail else "")
    return True, "package root exports the callable jscodeshift API and parses source"


def check_rust_entrypoint(candidate: Path) -> tuple[bool, str]:
    """Check that the public launcher executes a compiled Rust runner."""

    root = source_root(candidate)
    cargo = next(
        (root / relative for relative in ("rust-runner/Cargo.toml", "rust/Cargo.toml") if (root / relative).is_file()),
        None,
    )
    launchers = [root / relative for relative in ("bin/jscodeshift.sh", "bin/jscodeshift.js")]
    launcher = next((path for path in launchers if path.is_file()), None)
    if cargo is None or launcher is None:
        return False, "Rust runner manifest or launcher is missing"
    text = "\n".join(path.read_text(encoding="utf-8") for path in launchers if path.is_file())
    if "jscodeshift-rs" not in text:
        return False, "launcher does not invoke the compiled Rust runner"
    result = run_cli(candidate, ["--version"], cwd=root)
    if result.returncode != 0 or "jscodeshift:" not in result.stdout:
        return False, "Rust-backed version output was not observed through the public CLI"
    return True, "public CLI is backed by the compiled Rust runner"


def run_with_module_guard(
    candidate: Path,
    *,
    blocked: list[str],
    source_text: str = "const original = 1;\n",
    transform_text: str = "module.exports = (file, api) => api.jscodeshift(file.source).toSource();\n",
    cli_prefix: list[str] | None = None,
) -> tuple[bool, str]:
    """Run a public CLI transform while rejecting selected retained JS modules."""

    package = source_root(candidate).resolve()
    with tempfile.TemporaryDirectory(prefix="jscodeshift-engine-guard-") as raw:
        root = Path(raw)
        guard = root / "deny-retained-engine.js"
        guard.write_text(
            r'''
const Module = require('module');
const path = require('path');
const root = path.resolve(process.env.JSCODESHIFT_ENGINE_ROOT);
const blocked = JSON.parse(process.env.JSCODESHIFT_BLOCKED_MODULES || '[]');
const originalLoad = Module._load;
function retainedEngine(resolved) {
  if (typeof resolved !== 'string') return false;
  const relative = path.relative(root, path.resolve(resolved));
  return blocked.some(item => item.endsWith('/') ? relative.startsWith(item) : relative === item);
}
Module._load = function(request, parent, isMain) {
  const resolved = Module._resolveFilename(request, parent, isMain);
  if (retainedEngine(resolved)) {
    throw new Error(`retained JavaScript jscodeshift engine was loaded: ${resolved}`);
  }
  return originalLoad.apply(this, arguments);
};
'''.strip()
            + "\n",
            encoding="utf-8",
        )
        node_wrapper = root / "guarded-node"
        node_binary = shutil.which("node") or "/usr/local/bin/node"
        node_wrapper.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(node_binary)} --require {shlex.quote(str(guard))} \"$@\"\n",
            encoding="utf-8",
        )
        node_wrapper.chmod(0o755)
        environment = {
            "NODE_OPTIONS": f"--require={guard}",
            "JSCODESHIFT_ENGINE_ROOT": runtime_source_root(candidate),
            "JSCODESHIFT_BLOCKED_MODULES": json.dumps(blocked),
            # Rust implementations commonly launch a Node compatibility worker
            # through this documented hook.  Wrapping that hook guarantees the
            # module guard is loaded in every child process, not just in the
            # JavaScript launcher process.
            "JSCODESHIFT_NODE": str(node_wrapper),
        }
        source = root / "source.js"
        source.write_text(source_text, encoding="utf-8")
        transform = write_transform(
            root / "transform.js",
            transform_text,
        )
        result = run_cli(
            candidate,
            [*(cli_prefix or ["--run-in-band"]), "--transform", str(transform), str(source)],
            cwd=root,
            extra_env=environment,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            if "retained JavaScript jscodeshift engine was loaded" in output:
                return False, "runtime executed one of the retained JavaScript modules under test"
            return False, f"runtime ownership probe failed (rc={result.returncode})"
    return True, "runtime completed a real JavaScript transform without loading the retained modules under test"


def retained_engine_delegation(candidate: Path) -> str | None:
    """Return a concrete retained-engine delegation found in migration code.

    This is an architecture check, deliberately narrower than a source-file
    ban: JavaScript transforms remain supported, but the migrated runner must
    not invoke the original first-party runner, worker, parser, or core
    implementation to execute them.  A loader guard is still used below for
    runtime confirmation where process inheritance permits it.
    """

    root = source_root(candidate)
    scan_roots = [root / "rust", root / "rust-runner", root / "native"]
    retained_markers = (
        # A Rust worker that launches this bridge is still delegating AST and
        # transform execution to the original JavaScript engine: the bridge
        # imports src/getParser.js and src/core.js before invoking transforms.
        "worker_bridge.js",
        "src/Worker.js",
        "src/Runner.js",
        "src/core.js",
        "src/Collection.js",
        "src/getParser.js",
        "src/matchNode.js",
        "src/template.js",
    )
    for scan_root in scan_roots:
        if not scan_root.is_dir():
            continue
        for path in scan_root.rglob("*.rs"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for marker in retained_markers:
                if marker in text:
                    return f"{path.relative_to(root)} delegates to retained {marker}"
    return None


def check_rust_parser_printer_ownership(candidate: Path) -> tuple[bool, str]:
    """Verify parse/print work does not delegate to retained JS parser modules."""

    delegated = retained_engine_delegation(candidate)
    if delegated is not None:
        return False, f"parser/printer ownership failed: {delegated}"
    passed, detail = run_with_module_guard(
        candidate,
        blocked=["src/getParser.js", "parser/", "node_modules/recast/", "node_modules/ast-types/", "node_modules/@babel/parser/", "node_modules/flow-parser/"],
        source_text="const view = <Panel title=\"before\">{value?.name}</Panel>;\n",
        transform_text=(
            "module.exports = (file, api) => {\n"
            "  const j = api.jscodeshift; const root = j(file.source);\n"
            "  root.find(j.JSXAttribute, { name: { name: 'title' } }).forEach(p => { p.node.value.value = 'after'; });\n"
            "  return root.toSource({ quote: 'single' });\n"
            "};\n"
        ),
        cli_prefix=["--run-in-band", "--parser", "tsx"],
    )
    return passed, detail if passed else f"parser/printer ownership failed: {detail}"


def check_rust_core_collections_ownership(candidate: Path) -> tuple[bool, str]:
    """Verify the core API, collections, matching, and templates are Rust-owned."""

    delegated = retained_engine_delegation(candidate)
    if delegated is not None:
        return False, f"core/collections ownership failed: {delegated}"
    passed, detail = run_with_module_guard(
        candidate,
        blocked=["src/core.js", "src/Collection.js", "src/matchNode.js", "src/template.js", "src/collections/"],
        transform_text=(
            "module.exports = (file, api) => {\n"
            "  const j = api.jscodeshift; const root = j(file.source);\n"
            "  if (root.find(j.Identifier, { name: 'original' }).size() !== 1) throw new Error('collection find failed');\n"
            "  root.find(j.Identifier, { name: 'original' }).replaceWith(() => j.identifier('renamed'));\n"
            "  root.find(j.Program).get('body').push(j.template.statement`const generated = renamed;`);\n"
            "  return root.toSource();\n"
            "};\n"
        ),
    )
    return passed, detail if passed else f"core/collections ownership failed: {detail}"


def check_rust_worker_execution_ownership(candidate: Path) -> tuple[bool, str]:
    """Verify the public CLI does not delegate scheduling or transform work to old workers."""

    delegated = retained_engine_delegation(candidate)
    if delegated is not None:
        return False, f"worker execution ownership failed: {delegated}"
    passed, detail = run_with_module_guard(
        candidate,
        blocked=["src/Runner.js", "src/Worker.js"],
        cli_prefix=["--cpus", "2"],
    )
    return passed, detail if passed else f"worker execution ownership failed: {detail}"


def check_rust_package_api_ownership(candidate: Path) -> tuple[bool, str]:
    """Verify package-root helpers are backed by the migrated implementation."""

    package = source_root(candidate).resolve()
    with tempfile.TemporaryDirectory(prefix="jscodeshift-package-guard-") as raw:
        root = Path(raw)
        guard = root / "deny-retained-package-engine.js"
        blocked = ["src/core.js", "src/Collection.js", "src/getParser.js", "src/matchNode.js", "src/template.js", "src/collections/", "parser/"]
        guard.write_text(
            r'''
const Module = require('module');
const path = require('path');
const root = path.resolve(process.env.JSCODESHIFT_ENGINE_ROOT);
const blocked = JSON.parse(process.env.JSCODESHIFT_BLOCKED_MODULES || '[]');
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  const resolved = Module._resolveFilename(request, parent, isMain);
  if (typeof resolved === 'string') {
    const relative = path.relative(root, path.resolve(resolved));
    if (blocked.some(item => item.endsWith('/') ? relative.startsWith(item) : relative === item)) {
      throw new Error(`retained JavaScript jscodeshift engine was loaded: ${resolved}`);
    }
  }
  return originalLoad.apply(this, arguments);
};
'''.strip()
            + "\n",
            encoding="utf-8",
        )
        environment = {
            **os.environ,
            "NODE_OPTIONS": f"--require={guard}",
            "JSCODESHIFT_ENGINE_ROOT": str(package),
            "JSCODESHIFT_BLOCKED_MODULES": json.dumps(blocked),
            "JSCODESHIFT_PACKAGE": str(package),
        }

        export_probe = "const j=require(process.env.JSCODESHIFT_PACKAGE); if(typeof j !== 'function') process.exit(2); j('const x=1;');"
        exported = subprocess.run(
            ["node", "-e", export_probe],
            cwd=package,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        export_output = exported.stdout + exported.stderr
        if exported.returncode != 0 and "retained JavaScript jscodeshift engine was loaded" in export_output:
            return False, "package-root export executes retained JavaScript parser, core, collection, or template code"
        if exported.returncode != 0:
            return False, "package-root export is not backed by the migrated runtime"
    return True, "package-root helpers execute without loading retained first-party JavaScript engine modules"


def check(candidate: Path) -> dict[str, dict[str, str]]:
    """Run all private criteria and retain concise diagnostic evidence."""

    checks = {
        "cli-transform-api": check_cli_transform_api,
        "parser-and-transform-variants": check_parser_and_transform_variants,
        "file-selection-and-stdin": check_file_selection_and_stdin,
        "dry-run-print-and-reporting": check_dry_print_reporting,
        "parallel-workers-and-results": check_parallel_workers,
        "failure-and-exit-contract": check_failure_contract,
        "cli-surface-and-identity": check_cli_surface_and_identity,
        "silent-output-contract": check_silent_output_contract,
        "symlink-boundary": check_symlink_boundary,
        "parallel-failure-recovery": check_parallel_failure_recovery,
        "lifecycle-manifest": check_lifecycle_manifest,
        "custom-option-forwarding": check_custom_option_forwarding,
        "atomic-write-on-error": check_atomic_write_on_error,
        "parallel-result-determinism": check_parallel_result_determinism,
        "utf8-source-preservation": check_utf8_source_preservation,
        "ast-collections-and-builders": check_ast_collections_and_builders,
        "ast-formatting-and-comments": check_ast_formatting_and_comments,
        "ast-modern-syntax": check_ast_modern_syntax,
        "core-api-surface": check_core_api_surface,
        "collection-extensions": check_collection_extensions,
        "template-code-generation": check_template_code_generation,
        "package-root-export": check_package_root_export,
        "rust-runner-entrypoint": check_rust_entrypoint,
        "rust-parser-printer-ownership": check_rust_parser_printer_ownership,
        "rust-core-collections-ownership": check_rust_core_collections_ownership,
        "rust-worker-execution-ownership": check_rust_worker_execution_ownership,
        "rust-package-api-ownership": check_rust_package_api_ownership,
        "cross-feature-compatibility": check_cross_feature_compatibility,
        "package-boundary-compatibility": check_package_boundary_compatibility,
        "ast-composition-corpus": check_ast_composition_corpus,
        "worker-replay-consistency": check_worker_replay_consistency,
    }
    result: dict[str, dict[str, str]] = {}
    for criterion in CRITERIA:
        try:
            passed, detail = checks[criterion](candidate)
            result[criterion] = {"status": "pass" if passed else "fail", "detail": detail}
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            result[criterion] = {"status": "blocked", "detail": f"verifier setup failed: {exc}"}
    return result
