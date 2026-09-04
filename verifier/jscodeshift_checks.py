"""Private black-box checks for the jscodeshift JavaScript-to-Rust migration."""

from __future__ import annotations

import os
import subprocess
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
    "rust-runner-entrypoint",
)

SCENARIO_IDS = {
    "cli-transform-api": "jscodeshift.cli-transform-api",
    "parser-and-transform-variants": "jscodeshift.parser-and-transform-variants",
    "file-selection-and-stdin": "jscodeshift.file-selection-and-stdin",
    "dry-run-print-and-reporting": "jscodeshift.dry-run-print-and-reporting",
    "parallel-workers-and-results": "jscodeshift.parallel-workers-and-results",
    "failure-and-exit-contract": "jscodeshift.failure-and-exit-contract",
    "rust-runner-entrypoint": "jscodeshift.rust-runner-entrypoint",
}


def source_root(candidate: Path) -> Path:
    """Resolve the public codebase directory in a candidate workspace."""

    nested = candidate / "codebase"
    return nested if nested.is_dir() else candidate


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
) -> subprocess.CompletedProcess[str]:
    """Invoke the submitted CLI as a black box."""

    return subprocess.run(
        ["bash", str(cli_path(candidate)), *args],
        cwd=cwd,
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "NO_COLOR": "1"},
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

        silent_source = root / "silent.js"
        silent_source.write_text("const silent = true;\n", encoding="utf-8")
        silent_result = run_cli(
            candidate,
            ["--run-in-band", "--silent", "--transform", str(transform), str(silent_source)],
            cwd=root,
        )
        if silent_result.returncode != 0 or silent_result.stdout or silent_result.stderr:
            return False, "--silent did not suppress CLI output"
        if "// changed" not in silent_source.read_text(encoding="utf-8"):
            return False, "silent run did not still write the transformed file"

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
    return True, "dry run, print output, stats, and reports were preserved"


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


def check_rust_entrypoint(candidate: Path) -> tuple[bool, str]:
    """Check that the public launcher executes a compiled Rust runner."""

    root = source_root(candidate)
    cargo = root / "rust-runner/Cargo.toml"
    launcher = root / "bin/jscodeshift.sh"
    if not cargo.is_file() or not launcher.is_file():
        return False, "Rust runner manifest or launcher is missing"
    text = launcher.read_text(encoding="utf-8")
    if "rust-runner" not in text or "target/release" not in text:
        return False, "launcher does not invoke the compiled Rust runner"
    result = run_cli(candidate, ["--version"], cwd=root)
    if result.returncode != 0 or "runner: rust" not in result.stdout:
        return False, "Rust version output was not observed through the public CLI"
    return True, "public CLI is backed by the compiled Rust runner"


def check(candidate: Path) -> dict[str, dict[str, str]]:
    """Run all private criteria and retain concise diagnostic evidence."""

    checks = {
        "cli-transform-api": check_cli_transform_api,
        "parser-and-transform-variants": check_parser_and_transform_variants,
        "file-selection-and-stdin": check_file_selection_and_stdin,
        "dry-run-print-and-reporting": check_dry_print_reporting,
        "parallel-workers-and-results": check_parallel_workers,
        "failure-and-exit-contract": check_failure_contract,
        "rust-runner-entrypoint": check_rust_entrypoint,
    }
    result: dict[str, dict[str, str]] = {}
    for criterion in CRITERIA:
        try:
            passed, detail = checks[criterion](candidate)
            result[criterion] = {"status": "pass" if passed else "fail", "detail": detail}
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            result[criterion] = {"status": "blocked", "detail": f"verifier setup failed: {exc}"}
    return result
