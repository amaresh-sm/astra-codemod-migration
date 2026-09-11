"""Private black-box checks for the jscodeshift JavaScript-to-Rust migration."""

from __future__ import annotations

import os
import json
import hashlib
import re
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
    "rust-parser-babel-ownership",
    "rust-parser-typescript-ownership",
    "rust-parser-tsx-ownership",
    "rust-printer-comments-ownership",
    "rust-core-collections-ownership",
    "rust-core-builders-ownership",
    "rust-core-templates-ownership",
    "rust-core-nodepath-ownership",
    "rust-edge-ast-ownership",
    "rust-edge-cli-ownership",
    "rust-worker-multifile-ownership",
    "rust-worker-parallel-ownership",
    "rust-worker-failure-ownership",
    "rust-worker-determinism-ownership",
    "rust-package-root-ownership",
    "rust-package-clean-pack-ownership",
    "rust-package-guard-ownership",
    "rust-legacy-engine-boundary",
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
    "rust-parser-babel-ownership": "jscodeshift.rust-parser-babel-ownership",
    "rust-parser-typescript-ownership": "jscodeshift.rust-parser-typescript-ownership",
    "rust-parser-tsx-ownership": "jscodeshift.rust-parser-tsx-ownership",
    "rust-printer-comments-ownership": "jscodeshift.rust-printer-comments-ownership",
    "rust-core-collections-ownership": "jscodeshift.rust-core-collections-ownership",
    "rust-core-builders-ownership": "jscodeshift.rust-core-builders-ownership",
    "rust-core-templates-ownership": "jscodeshift.rust-core-templates-ownership",
    "rust-core-nodepath-ownership": "jscodeshift.rust-core-nodepath-ownership",
    "rust-edge-ast-ownership": "jscodeshift.rust-edge-ast-ownership",
    "rust-edge-cli-ownership": "jscodeshift.rust-edge-cli-ownership",
    "rust-worker-multifile-ownership": "jscodeshift.rust-worker-multifile-ownership",
    "rust-worker-parallel-ownership": "jscodeshift.rust-worker-parallel-ownership",
    "rust-worker-failure-ownership": "jscodeshift.rust-worker-failure-ownership",
    "rust-worker-determinism-ownership": "jscodeshift.rust-worker-determinism-ownership",
    "rust-package-root-ownership": "jscodeshift.rust-package-root-ownership",
    "rust-package-clean-pack-ownership": "jscodeshift.rust-package-clean-pack-ownership",
    "rust-package-guard-ownership": "jscodeshift.rust-package-guard-ownership",
    "rust-legacy-engine-boundary": "jscodeshift.rust-legacy-engine-boundary",
    "cross-feature-compatibility": "jscodeshift.cross-feature-compatibility",
    "package-boundary-compatibility": "jscodeshift.package-boundary-compatibility",
    "ast-composition-corpus": "jscodeshift.ast-composition-corpus",
    "worker-replay-consistency": "jscodeshift.worker-replay-consistency",
}


def source_root(candidate: Path) -> Path:
    """Resolve the public codebase directory in a candidate workspace."""

    nested = candidate / "codebase"
    return nested if nested.is_dir() else candidate


ENGINE_SOURCE_SUFFIXES = frozenset({".cjs", ".js", ".mjs", ".ts", ".tsx"})
ENGINE_EXCLUDED_PARTS = frozenset({".git", "node_modules", "target", ".cargo-home"})

# JavaScript is allowed only at the compatibility boundary.  The boundary
# keeps customer-authored transforms working; parsing, printing, collections,
# and scheduling must remain in the Rust implementation.  This is an explicit
# policy rather than a filename heuristic for detecting the old engine.
ALLOWED_JS_BRIDGE_PATHS = frozenset({
    "index.js",
    "bin/jscodeshift.js",
    "rust-compat.js",
    "rust-compat-worker.js",
})

# The bridge exists solely because customer transforms are JavaScript. It may
# load a transform, marshal file/options data, and forward requests to Rust;
# it must not become a second implementation of the jscodeshift engine.
# These capabilities deliberately describe behavior rather than prescribed
# filenames or the historical upstream source layout.
BRIDGE_ENGINE_CAPABILITIES = {
    "collection runtime": re.compile(
        r"\b(?:find|filter|map|forEach|replaceWith|paths|nodes|at|isOfType|getTypes|childElements|childNodes|renameTo)\s*\("
    ),
    "AST node projection": re.compile(r"\b(?:nodeFromDescriptor|makePath)\s*\(|\bObject\.defineProperty\s*\("),
    "AST builders": re.compile(
        r"\b(?:identifier|literal|variableDeclarator|variableDeclaration|memberExpression|callExpression|expressionStatement)\s*\("
    ),
    "template generation": re.compile(r"\b(?:template|asyncExpression)\s*\("),
    "printing or source mutation": re.compile(r"\b(?:toSource|renderNode|replaceAll|renameIdentifier|flush|patch)\s*\("),
}


def _javascript_code_without_comments_or_literals(source: str) -> str:
    """Remove comments and literals before evaluating bridge capabilities.

    This is intentionally a small lexical pass, not a JavaScript parser. It
    avoids rejecting harmless documentation or diagnostic strings that happen
    to name jscodeshift methods while retaining executable identifiers and
    class declarations for the bridge-boundary audit.
    """

    output: list[str] = []
    index = 0
    length = len(source)
    quote: str | None = None
    while index < length:
        char = source[index]
        next_char = source[index + 1] if index + 1 < length else ""
        if quote is not None:
            if char == "\\":
                output.append(" ")
                if index + 1 < length:
                    output.append(" ")
                    index += 2
                    continue
            elif char == quote:
                quote = None
            output.append("\n" if char == "\n" else " ")
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            output.append(" ")
            index += 1
            continue
        if char == "/" and next_char == "/":
            while index < length and source[index] != "\n":
                output.append(" ")
                index += 1
            continue
        if char == "/" and next_char == "*":
            output.extend((" ", " "))
            index += 2
            while index < length:
                if source[index] == "*" and index + 1 < length and source[index + 1] == "/":
                    output.extend((" ", " "))
                    index += 2
                    break
                output.append("\n" if source[index] == "\n" else " ")
                index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def bridge_engine_findings(candidate: Path) -> list[str]:
    """Identify first-party engine behavior implemented in the allowed bridge.

    A legitimate bridge can be a loader and a generic protocol adapter. A
    bridge that combines runtime classes with several independent AST-engine
    capabilities is a hybrid engine, even if it invokes a Rust binary for a
    cosmetic or partial operation. The check intentionally requires a
    combination of signals to avoid rejecting simple adapter glue.
    """

    package = source_root(candidate)
    findings: list[str] = []
    for relative in sorted(ALLOWED_JS_BRIDGE_PATHS):
        path = package / relative
        if not path.is_file():
            continue
        try:
            code = _javascript_code_without_comments_or_literals(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        classes = sorted(set(re.findall(r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)", code)))
        capabilities = sorted(
            label for label, pattern in BRIDGE_ENGINE_CAPABILITIES.items() if pattern.search(code)
        )
        # A thin adapter needs neither its own runtime object model nor a
        # collection of AST operations. Requiring both signals keeps this a
        # semantic ownership guard rather than a source-size/file-name rule.
        if classes and len(capabilities) >= 2:
            findings.append(
                f"{relative} defines runtime classes ({', '.join(classes)}) and engine capabilities ({', '.join(capabilities)})"
            )
        elif len(capabilities) >= 4:
            findings.append(f"{relative} implements multiple AST-engine capabilities ({', '.join(capabilities)})")
    return findings


def public_source_root() -> Path | None:
    """Locate the immutable public source snapshot mounted for verification."""

    candidates = []
    configured = os.environ.get("ASTRA_PUBLIC_ROOT")
    if configured:
        candidates.append(Path(configured))
    candidates.extend((Path("/input/public/codebase"), Path("/input/public")))
    for candidate in candidates:
        if candidate.is_dir() and any((candidate / name).exists() for name in ("src", "parser", "index.js")):
            return candidate
    return None


def file_digest(path: Path) -> str | None:
    """Return a stable digest for one source file, or ``None`` if unreadable."""

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def legacy_engine_paths(candidate: Path) -> set[str]:
    """Return retained-engine paths to quarantine in a staged candidate.

    The public source snapshot supplies content fingerprints, so an upstream
    JavaScript engine copied to a different filename is still quarantined.
    Directory fallbacks preserve compatibility with local verifier tests where
    the public mount is unavailable.  This function intentionally ignores Rust
    source text, comments, and filenames when deciding ownership.
    """

    package = source_root(candidate)
    paths: set[str] = set()
    for relative in (
        "src",
        "parser",
        "node_modules/recast",
        "node_modules/ast-types",
        "node_modules/@babel/parser",
        "node_modules/flow-parser",
    ):
        path = package / relative
        if path.exists() or path.is_symlink():
            paths.add(relative)

    public_root = public_source_root()
    if public_root is None:
        return paths

    fingerprints: set[str] = set()
    for path in public_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ENGINE_SOURCE_SUFFIXES:
            continue
        if ENGINE_EXCLUDED_PARTS.intersection(path.relative_to(public_root).parts):
            continue
        digest = file_digest(path)
        if digest:
            fingerprints.add(digest)

    if not fingerprints:
        return paths
    for path in package.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ENGINE_SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(package)
        if ENGINE_EXCLUDED_PARTS.intersection(relative.parts):
            continue
        if file_digest(path) in fingerprints:
            paths.add(relative.as_posix())
    return paths


def legacy_engine_module_patterns(candidate: Path) -> list[str]:
    """Convert quarantined paths into module-loader relative patterns."""

    package = source_root(candidate)
    patterns: list[str] = []
    for relative in legacy_engine_paths(candidate):
        path = package / relative
        patterns.append(relative + "/" if path.is_dir() else relative)
    return sorted(patterns)


def retained_legacy_engine_copies(candidate: Path) -> set[str]:
    """Find exact copies of the public first-party JS engine retained in a candidate.

    The migration contract permits a small compatibility bridge, but not a
    second copy of the original implementation hidden under ``src``, ``dist``,
    or a renamed parser/worker path. Content fingerprints make this independent
    of the candidate's chosen filenames. If the public snapshot is unavailable,
    return no static findings and let the runtime quarantine probes decide.
    """

    if public_source_root() is None:
        return set()
    package = source_root(candidate)
    retained: set[str] = set()
    for relative in legacy_engine_paths(candidate):
        path = package / relative
        if not path.is_file() or path.suffix.lower() not in ENGINE_SOURCE_SUFFIXES:
            continue
        if relative.startswith("sample/"):
            continue
        retained.add(relative)
    return retained


def _remove_non_bridge_sources(package: Path) -> list[str]:
    """Remove every submitted source file except the explicit JS bridge.

    The staged copy is disposable, so unlinking is safe and avoids changing a
    candidate's checkout.  User transforms are created outside ``package``
    and remain available to the compatibility worker.
    """

    removed: list[str] = []
    for path in sorted(package.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        if not (path.is_file() or path.is_symlink()) or path.suffix.lower() not in ENGINE_SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(package).as_posix()
        if relative in ALLOWED_JS_BRIDGE_PATHS:
            continue
        try:
            path.unlink()
            removed.append(relative)
        except OSError:
            # The caller reports a failed probe if the resulting CLI cannot
            # start.  Do not turn a candidate-file cleanup issue into a
            # verifier crash.
            continue
    return removed


def _find_native_binary(package: Path) -> Path | None:
    """Find the built Rust executable exposed by the candidate launcher."""

    candidates: list[Path] = []
    target_directories = list(package.rglob("target/release")) + list(package.rglob("target/debug"))
    for directory in target_directories:
        if not directory.is_dir():
            continue
        relative_directory = directory.relative_to(package)
        if {".git", "node_modules", ".cargo-home"}.intersection(relative_directory.parts):
            continue
        candidates.extend(
            path for path in directory.iterdir()
            if path.is_file() and path.name != ".rustc_info.json" and os.access(path, os.X_OK)
        )
    return sorted(
        candidates,
        key=lambda path: (
            "jscodeshift" not in path.name.lower(),
            "release" not in path.parts,
            path.name,
        ),
    )[0] if candidates else None


def _module_trace_environment(package: Path, trace_root: Path) -> dict[str, str]:
    """Trace Node workers and the compiled Rust process used by the probes."""

    trace = trace_root / "module-trace.js"
    trace.write_text(
        r'''
const fs = require('fs');
const path = require('path');
const Module = require('module');
const traceFile = process.env.JSCODESHIFT_MODULE_TRACE;
if (traceFile) {
  fs.appendFileSync(traceFile, JSON.stringify({kind: 'node-process', pid: process.pid}) + '\n');
}
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  let resolved = null;
  try { resolved = Module._resolveFilename(request, parent, isMain); } catch (_) {}
  if (traceFile && typeof resolved === 'string') {
    fs.appendFileSync(traceFile, JSON.stringify({kind: 'module', resolved}) + '\n');
  }
  return originalLoad.apply(this, arguments);
};
'''.strip()
        + "\n",
        encoding="utf-8",
    )
    node_wrapper = trace_root / "node"
    node_binary = shutil.which("node") or "/usr/local/bin/node"
    node_wrapper.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(node_binary)} --require {shlex.quote(str(trace))} \"$@\"\n",
        encoding="utf-8",
    )
    node_wrapper.chmod(0o755)
    original_path = os.environ.get("PATH", "")
    environment = {
        "PATH": f"{trace_root}{os.pathsep}{original_path}",
        "JSCODESHIFT_ENGINE_ROOT": str(package.resolve()),
        "JSCODESHIFT_MODULE_TRACE": str(trace_root / "modules.jsonl"),
    }
    native_binary = _find_native_binary(package)
    if native_binary is not None:
        native_wrapper = trace_root / "native-runner"
        native_wrapper.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' '{\"kind\":\"native-process\"}' >> \"$JSCODESHIFT_MODULE_TRACE\"\n"
            "exec \"$JSCODESHIFT_REAL_NATIVE\" \"$@\"\n",
            encoding="utf-8",
        )
        native_wrapper.chmod(0o755)
        environment.update({
            "JSCODESHIFT_BINARY": str(native_wrapper),
            "JSCODESHIFT_NATIVE_ENGINE": str(native_wrapper),
            "JSCODESHIFT_REAL_NATIVE": str(native_binary),
        })
    return environment


def _trace_loaded_package_modules(trace_file: Path, package: Path) -> tuple[set[str], int, int]:
    """Return loaded source paths plus traced Node and native process counts."""

    loaded: set[str] = set()
    node_processes = 0
    native_processes = 0
    if not trace_file.is_file():
        return loaded, node_processes, native_processes
    package_root = package.resolve()
    for raw in trace_file.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("kind") == "node-process":
            node_processes += 1
            continue
        if isinstance(event, dict) and event.get("kind") == "native-process":
            native_processes += 1
            continue
        resolved = event.get("resolved") if isinstance(event, dict) else None
        if not isinstance(resolved, str):
            continue
        path = Path(resolved)
        try:
            relative = path.resolve().relative_to(package_root).as_posix()
        except ValueError:
            continue
        if path.suffix.lower() in ENGINE_SOURCE_SUFFIXES:
            loaded.add(relative)
    return loaded, node_processes, native_processes


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

        # Exercise a realistic customer-authored JSX/TSX transform.  This is
        # intentionally kept inside the existing AST-composition criterion:
        # ReactDOM is representative application code, not a new library
        # feature.  The cases cover import rewriting, aliases, multiple
        # matches, existing client imports, false-positive avoidance, comment
        # preservation, and a byte-for-byte no-op.
        react_files = {
            "project/react-basic.jsx": (
                'import React from "react";\n'
                'import ReactDOM from "react-dom";\n\n'
                'ReactDOM.render(<App />, root);\n'
            ),
            "project/react-multiple.jsx": (
                'import DOM from "react-dom";\n'
                'const text = "ReactDOM.render(<Fake />, root);";\n'
                'DOM.render(<First />, root);\n'
                'Other.render(<Ignored />, root);\n'
                'DOM.render(<Second />, otherRoot);\n'
            ),
            "project/react-existing-client.jsx": (
                'import ReactDOM from "react-dom/client";\n\n'
                'ReactDOM.render(<App />, root);\n'
            ),
            "project/react-no-match.jsx": (
                'const text = "ReactDOM.render(<Fake />, root);";\n'
                'Other.render(<Ignored />, root);\n'
            ),
            "project/react-comments.tsx": (
                '// keep this integration comment\n'
                'interface Props { root: HTMLElement }\n'
                'import DOM from "react-dom";\n\n'
                'const view = <Widget />;\n'
                'DOM.render(\n'
                '  view,\n'
                '  container\n'
                ');\n'
            ),
        }
        for relative, content in react_files.items():
            (root / relative).write_text(content, encoding="utf-8")

        react_transform = write_transform(
            root / "react-migration-transform.js",
            r'''
module.exports = function(file, api) {
  const j = api.jscodeshift;
  const ast = j(file.source);
  const domLocals = new Set();

  ast.find(j.ImportDeclaration).forEach(path => {
    const source = path.node.source.value;
    if (source !== 'react-dom' && source !== 'react-dom/client') return;
    const defaultImport = (path.node.specifiers || []).find(
      specifier => specifier.type === 'ImportDefaultSpecifier'
    );
    if (!defaultImport) return;
    domLocals.add(defaultImport.local.name);
    if (source === 'react-dom') path.node.source.value = 'react-dom/client';
  });

  let changed = false;
  const transformed = ast.find(j.CallExpression).replaceWith(path => {
    const call = path.node;
    const callee = call.callee;
    if (!callee || callee.type !== 'MemberExpression' || callee.computed ||
        callee.property.type !== 'Identifier' || callee.property.name !== 'render' ||
        callee.object.type !== 'Identifier' || !domLocals.has(callee.object.name) ||
        call.arguments.length !== 2) {
      return call;
    }
    changed = true;
    const root = j.callExpression(
      j.memberExpression(callee.object, j.identifier('createRoot')),
      [call.arguments[1]]
    );
    return j.callExpression(j.memberExpression(root, j.identifier('render')), [call.arguments[0]]);
  });

  return changed ? transformed.toSource({ quote: 'double' }) : file.source;
};
'''.strip()
            + "\n",
        )
        react_result = run_cli(
            candidate,
            ["--cpus", "2", "--parser", "tsx", "--transform", str(react_transform), "project"],
            cwd=root,
        )
        if react_result.returncode != 0:
            return False, f"React AST corpus transform failed (rc={react_result.returncode})"

        basic = (root / "project/react-basic.jsx").read_text(encoding="utf-8")
        if (
            'import ReactDOM from "react-dom/client";' not in basic
            or "ReactDOM.createRoot(root).render(<App />);" not in basic
            or "ReactDOM.render" in basic
        ):
            return False, "React basic import/call migration did not produce the expected output"

        multiple = (root / "project/react-multiple.jsx").read_text(encoding="utf-8")
        if (
            multiple.count("DOM.createRoot(") != 2
            or "Other.render(<Ignored />, root);" not in multiple
            or '"ReactDOM.render(<Fake />, root);"' not in multiple
        ):
            return False, "React aliases, multiple calls, or false-positive guards failed"

        existing = (root / "project/react-existing-client.jsx").read_text(encoding="utf-8")
        if (
            existing.count('from "react-dom/client"') != 1
            or "ReactDOM.createRoot(root).render(<App />);" not in existing
        ):
            return False, "existing react-dom/client import was not handled without duplication"

        no_match_path = root / "project/react-no-match.jsx"
        if no_match_path.read_text(encoding="utf-8") != react_files["project/react-no-match.jsx"]:
            return False, "no-match React source was not preserved byte-for-byte"

        comments = (root / "project/react-comments.tsx").read_text(encoding="utf-8")
        if (
            "keep this integration comment" not in comments
            or "interface Props" not in comments
            or "DOM.createRoot(container).render(view);" not in comments.replace("\n", "")
        ):
            return False, "React TSX comments, formatting, or call migration was not preserved"
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
    """Check that the public launcher executes a compiled Rust runner.

    This intentionally checks the migration boundary, not a prescribed
    directory layout or executable name.  A candidate may keep its Cargo
    package at the source root, in ``rust/``, or in another small first-party
    subdirectory and may name the executable ``jscodeshift`` rather than
    ``jscodeshift-rs``.
    """

    root = source_root(candidate)
    ignored_parts = {"node_modules", "target", ".git", ".cargo-home"}
    cargo_manifests = [
        path
        for path in root.rglob("Cargo.toml")
        if not any(part in ignored_parts for part in path.relative_to(root).parts)
        and len(path.relative_to(root).parts) <= 3
    ]
    launchers = [root / relative for relative in ("bin/jscodeshift.sh", "bin/jscodeshift.js")]
    launcher = next((path for path in launchers if path.is_file()), None)
    if not cargo_manifests or launcher is None:
        return False, "Rust runner manifest or launcher is missing"

    has_rust_source = any(any(manifest.parent.rglob("*.rs")) for manifest in cargo_manifests)
    if not has_rust_source:
        return False, "Rust runner manifest has no Rust source files"

    text = "\n".join(path.read_text(encoding="utf-8") for path in launchers if path.is_file())
    native_launcher_signals = (
        "JSCODESHIFT_BINARY",
        "cargo run",
        "target/release",
        "target/debug",
        "'target', 'release'",
        "'target', 'debug'",
        '"target", "release"',
        '"target", "debug"',
    )
    if not any(signal in text for signal in native_launcher_signals):
        return False, "launcher does not invoke the compiled Rust runner"
    result = run_cli(candidate, ["--version"], cwd=root)
    if result.returncode != 0 or "jscodeshift:" not in result.stdout:
        return False, "Rust-backed version output was not observed through the public CLI"
    return True, "public CLI is backed by the compiled Rust runner"


def run_with_bridge_only_files(
    candidate: Path,
    *,
    source_files: dict[str, str],
    transform_text: str,
    cli_prefix: list[str] | None = None,
    target: str = "project",
    stdin_paths: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], str | None]:
    """Run a probe after removing all submitted JS except the bridge.

    This is stronger than hiding known legacy directories: a rewritten JS
    engine under an unfamiliar filename is removed too.  A Node wrapper traces
    every child worker's module loads, so the probe also fails if an
    unapproved package-relative JavaScript implementation is executed.
    """

    with tempfile.TemporaryDirectory(prefix="jscodeshift-bridge-only-") as raw:
        root = Path(raw)
        staged = root / "candidate"
        try:
            shutil.copytree(candidate, staged, symlinks=True, copy_function=os.link)
        except OSError:
            if staged.exists():
                shutil.rmtree(staged)
            shutil.copytree(candidate, staged, symlinks=True)

        package = source_root(staged)
        _remove_non_bridge_sources(package)
        trace_environment = _module_trace_environment(package, root)

        for relative, content in source_files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        transform = write_transform(root / "transform.js", transform_text)
        args = [*(cli_prefix or ["--run-in-band"]), "--transform", str(transform), str(root / target)]
        stdin = None
        if stdin_paths:
            stdin = "\n".join(str(root / relative) for relative in source_files) + "\n"
            args = [arg for arg in args if arg != str(root / target)]
        result = run_cli(staged, args, cwd=root, stdin=stdin, extra_env=trace_environment)

        trace_file = root / "modules.jsonl"
        loaded, node_processes, native_processes = _trace_loaded_package_modules(trace_file, package)
        disallowed = sorted(loaded - ALLOWED_JS_BRIDGE_PATHS)
        trace_error: str | None = None
        if disallowed:
            trace_error = "unapproved package JavaScript loaded: " + ", ".join(disallowed)
        elif node_processes == 0:
            trace_error = "no traced Node compatibility process was observed"
        elif native_processes == 0:
            trace_error = "no traced compiled Rust process was observed"

        contents = {}
        for relative in source_files:
            path = root / relative
            contents[relative] = path.read_text(encoding="utf-8") if path.exists() else ""
        return result, contents, trace_error


def ownership_probe(
    candidate: Path,
    *,
    label: str,
    source_files: dict[str, str],
    transform_text: str,
    marker: str,
    cli_prefix: list[str] | None = None,
) -> tuple[bool, str]:
    """Run one independent ownership probe and report only its own boundary."""

    result, contents, trace_error = run_with_bridge_only_files(
        candidate,
        source_files=source_files,
        transform_text=transform_text,
        cli_prefix=cli_prefix,
    )
    if trace_error:
        return False, f"{label} ownership trace failed: {trace_error}"
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        return False, f"{label} ownership probe failed (rc={result.returncode}){suffix}"
    if not contents or not all(marker in content for content in contents.values()):
        missing = [name for name, content in contents.items() if marker not in content]
        return False, f"{label} ownership probe did not produce the expected native result: {', '.join(missing)}"
    return True, f"{label} completed with only the explicit JS bridge"


def check_rust_parser_babel_ownership(candidate: Path) -> tuple[bool, str]:
    return ownership_probe(
        candidate,
        label="Babel parser/printer",
        source_files={"project/babel.js": "const value = 1;\n"},
        transform_text="module.exports = (file, api) => api.jscodeshift(file.source).toSource() + '\\n// babel-owned';\n",
        marker="babel-owned",
    )


def check_rust_parser_typescript_ownership(candidate: Path) -> tuple[bool, str]:
    return ownership_probe(
        candidate,
        label="TypeScript parser",
        source_files={"project/types.ts": "type Value = string; const value: Value = 'ok';\n"},
        transform_text=(
            "module.exports = (file, api) => { const j = api.jscodeshift; const root = j(file.source); "
            "if (root.find(j.TSTypeAliasDeclaration).size() !== 1) throw new Error('TS parser failed'); "
            "return file.source + '\\n// typescript-owned'; };\n"
        ),
        marker="typescript-owned",
        cli_prefix=["--run-in-band", "--parser", "ts"],
    )


def check_rust_parser_tsx_ownership(candidate: Path) -> tuple[bool, str]:
    return ownership_probe(
        candidate,
        label="TSX parser",
        source_files={"project/view.tsx": "const view = <Panel title=\"before\">{value?.name}</Panel>;\n"},
        transform_text=(
            "module.exports = (file, api) => { const j = api.jscodeshift; const root = j(file.source); "
            "if (root.find(j.JSXElement).size() !== 1) throw new Error('TSX parser failed'); "
            "return file.source + '\\n// tsx-owned'; };\n"
        ),
        marker="tsx-owned",
        cli_prefix=["--run-in-band", "--parser", "tsx"],
    )


def check_rust_printer_comments_ownership(candidate: Path) -> tuple[bool, str]:
    return ownership_probe(
        candidate,
        label="comment-preserving printer",
        source_files={"project/comments.js": "// preserve this comment\nconst value = \"old\";\n"},
        transform_text=(
            "module.exports = (file, api) => { const j = api.jscodeshift; const root = j(file.source); "
            "root.find(j.Literal, {value:'old'}).forEach(p => {p.node.value='new';}); "
            "return root.toSource({quote:'single'}) + '\\n// printer-owned'; };\n"
        ),
        marker="printer-owned",
    )


def check_rust_core_builders_ownership(candidate: Path) -> tuple[bool, str]:
    return ownership_probe(
        candidate,
        label="core builders",
        source_files={"project/builders.js": "const existing = 1;\n"},
        transform_text=(
            "module.exports = (file, api) => { const j = api.jscodeshift; const root = j(file.source); "
            "root.find(j.Program).get('body').value.push(j.variableDeclaration('const',[j.variableDeclarator(j.identifier('builderOwned'),j.literal(1))])); "
            "return root.toSource(); };\n"
        ),
        marker="builderOwned",
    )


def check_rust_core_templates_ownership(candidate: Path) -> tuple[bool, str]:
    return ownership_probe(
        candidate,
        label="template generation",
        source_files={"project/templates.js": "const existing = 1;\n"},
        transform_text=(
            "module.exports = (file, api) => { const j = api.jscodeshift; const root = j(file.source); "
            "const quasi = ['const templateOwned = 42;']; quasi.raw = quasi; "
            "root.find(j.Program).get('body').value.push(j.template.statement(quasi)); return root.toSource(); };\n"
        ),
        marker="templateOwned",
    )


def check_rust_core_nodepath_ownership(candidate: Path) -> tuple[bool, str]:
    return ownership_probe(
        candidate,
        label="NodePath accessors",
        source_files={"project/nodepath.js": "const pathOwned = 1;\n"},
        transform_text=(
            "module.exports = (file, api) => { const j = api.jscodeshift; const root = j(file.source); "
            "const paths = root.find(j.VariableDeclarator).paths(); if (paths.length !== 1 || paths[0].get('id').value.name !== 'pathOwned') throw new Error('NodePath failed'); "
            "return file.source + '\\n// nodepath-owned'; };\n"
        ),
        marker="nodepath-owned",
    )


def check_rust_edge_ast_ownership(candidate: Path) -> tuple[bool, str]:
    """Exercise optional chaining, nullish coalescing, TS types, and TSX together."""

    return ownership_probe(
        candidate,
        label="edge-case AST syntax",
        source_files={
            "project/edge.tsx": (
                "type Item = { value: string };\n"
                "const render = (item?: Item) => <Box data-value={item?.value ?? 'fallback'} />;\n"
            )
        },
        transform_text=(
            "module.exports = (file, api) => { const j = api.jscodeshift; const root = j(file.source); "
            "if (root.find(j.JSXElement).size() !== 1 || root.find(j.TSTypeAliasDeclaration).size() !== 1) "
            "throw new Error('edge AST syntax failed'); return file.source + '\\n// edge-ast-owned'; };\n"
        ),
        marker="edge-ast-owned",
        cli_prefix=["--run-in-band", "--parser", "tsx"],
    )


def check_rust_edge_cli_ownership(candidate: Path) -> tuple[bool, str]:
    """Exercise stdin file discovery and extension filtering independently."""

    result, contents, trace_error = run_with_bridge_only_files(
        candidate,
        source_files={
            "project/edge.js": "const edge = 1;\n",
            "project/ignored.txt": "not a transform input\n",
        },
        transform_text="module.exports = file => file.source + '\\n// edge-cli-owned';\n",
        cli_prefix=["--run-in-band", "--stdin", "--extensions", "js"],
        stdin_paths=True,
    )
    if trace_error:
        return False, f"edge-case CLI ownership trace failed: {trace_error}"
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        return False, f"edge-case CLI ownership probe failed (rc={result.returncode}){suffix}"
    if "edge-cli-owned" not in contents["project/edge.js"] or "edge-cli-owned" in contents["project/ignored.txt"]:
        return False, "edge-case CLI ownership probe did not preserve stdin and extension boundaries"
    return True, "stdin and extension filtering completed with only the explicit JS bridge"


def _worker_files() -> dict[str, str]:
    return {f"project/file-{index}.js": f"const workerValue{index} = {index};\n" for index in range(6)}


def check_rust_worker_multifile_ownership(candidate: Path) -> tuple[bool, str]:
    return ownership_probe(
        candidate,
        label="multi-file worker execution",
        source_files=_worker_files(),
        transform_text="module.exports = file => file.source + '\\n// multifile-owned';\n",
        marker="multifile-owned",
        cli_prefix=["--cpus", "1"],
    )


def check_rust_worker_parallel_ownership(candidate: Path) -> tuple[bool, str]:
    return ownership_probe(
        candidate,
        label="parallel worker execution",
        source_files=_worker_files(),
        transform_text="module.exports = file => file.source + '\\n// parallel-owned';\n",
        marker="parallel-owned",
        cli_prefix=["--cpus", "2"],
    )


def check_rust_worker_failure_ownership(candidate: Path) -> tuple[bool, str]:
    files = {"project/good-a.js": "const a = 1;\n", "project/bad.js": "const bad = 1;\n", "project/good-b.js": "const b = 1;\n"}
    result, contents, trace_error = run_with_bridge_only_files(
        candidate,
        source_files=files,
        transform_text=(
            "module.exports = file => { if (file.path.endsWith('bad.js')) throw new Error('intentional worker failure'); "
            "return file.source + '\\n// recovery-owned'; };\n"
        ),
        cli_prefix=["--cpus", "2", "--fail-on-error"],
    )
    if trace_error:
        return False, f"worker failure ownership trace failed: {trace_error}"
    good = all("recovery-owned" in contents[name] for name in ("project/good-a.js", "project/good-b.js"))
    if result.returncode == 0 or not good:
        return False, f"worker failure recovery ownership failed (rc={result.returncode})"
    return True, "parallel worker failure recovery preserved successful files with only the explicit JS bridge"


def check_rust_worker_determinism_ownership(candidate: Path) -> tuple[bool, str]:
    files = _worker_files()
    transform = "module.exports = file => file.source + '\\n// deterministic-owned';\n"
    first_result, first, first_trace_error = run_with_bridge_only_files(candidate, source_files=files, transform_text=transform, cli_prefix=["--cpus", "2"])
    second_result, second, second_trace_error = run_with_bridge_only_files(candidate, source_files=files, transform_text=transform, cli_prefix=["--cpus", "2"])
    if first_trace_error or second_trace_error:
        return False, "parallel worker ownership trace failed"
    if first_result.returncode != 0 or second_result.returncode != 0 or first != second:
        return False, "parallel worker replay changed outcomes with only the explicit JS bridge"
    return True, "parallel worker replay was deterministic with only the explicit JS bridge"


def check_rust_package_root_ownership(candidate: Path) -> tuple[bool, str]:
    package = source_root(candidate).resolve()
    probe = (
        "const j=require(process.env.JSCODESHIFT_PACKAGE);"
        "if(typeof j!=='function'||typeof j.withParser!=='function'||"
        "(!j.template || typeof j.template.statement!=='function')) process.exit(2);"
        "const root=j('const value=1;'); if(!root.find(j.Identifier).size()) process.exit(3);"
    )
    result = subprocess.run(
        ["node", "-e", probe],
        cwd=package,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "JSCODESHIFT_PACKAGE": str(package)},
    )
    if result.returncode != 0:
        return False, "package-root API did not expose callable parser, collections, and template helpers"
    return True, "package-root API exposes callable parser, collections, and template helpers"


def check_rust_package_clean_pack_ownership(candidate: Path) -> tuple[bool, str]:
    """Verify a packed artifact still works after non-bridge JS is removed."""

    with tempfile.TemporaryDirectory(prefix="jscodeshift-clean-pack-ownership-") as raw:
        work = Path(raw)
        staged = work / "candidate"
        try:
            shutil.copytree(candidate, staged, symlinks=True, copy_function=os.link)
        except OSError:
            if staged.exists():
                shutil.rmtree(staged)
            shutil.copytree(candidate, staged, symlinks=True)
        package_root = source_root(staged)
        _remove_non_bridge_sources(package_root)
        packed = work / "packed"
        packed.mkdir()
        packed_result = subprocess.run(
            ["npm", "pack", "--ignore-scripts", "--json", "--pack-destination", str(packed)],
            cwd=package_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
        tarballs = sorted(packed.glob("*.tgz"))
        if packed_result.returncode != 0 or len(tarballs) != 1:
            return False, "clean package ownership npm pack failed"
        unpacked = work / "unpacked"
        unpacked.mkdir()
        with tarfile.open(tarballs[0], "r:gz") as archive:
            base = unpacked.resolve()
            for member in archive.getmembers():
                target = (unpacked / member.name).resolve()
                if target != base and base not in target.parents:
                    return False, "clean package archive contains an unsafe path"
            archive.extractall(unpacked)
        package = unpacked / "package"
        disallowed = sorted(
            path.relative_to(package).as_posix()
            for path in package.rglob("*")
            if path.is_file()
            and path.suffix.lower() in ENGINE_SOURCE_SUFFIXES
            and path.relative_to(package).as_posix() not in ALLOWED_JS_BRIDGE_PATHS
        )
        if disallowed:
            return False, "clean packed artifact retains non-bridge JavaScript: " + ", ".join(disallowed[:8])
        bins = json.loads((package / "package.json").read_text(encoding="utf-8")).get("bin", {})
        if isinstance(bins, str):
            bins = {"jscodeshift": bins}
        if not isinstance(bins, dict) or not bins:
            return False, "clean packed artifact has no CLI bin"
        bin_path = package / next(iter(bins.values()))
        smoke = subprocess.run(
            [str(bin_path), "--version"], cwd=work, text=True, capture_output=True, check=False
        )
        if smoke.returncode != 0 or "jscodeshift:" not in smoke.stdout:
            return False, "clean packed Rust CLI did not execute"
    return True, "clean packed artifact executes with only the explicit JS bridge"


def check_rust_package_guard_ownership(candidate: Path) -> tuple[bool, str]:
    """Trace package-root loading and reject any non-bridge JS implementation."""

    bridge_findings = bridge_engine_findings(candidate)
    if bridge_findings:
        return False, "compatibility bridge contains first-party engine logic: " + "; ".join(bridge_findings)

    with tempfile.TemporaryDirectory(prefix="jscodeshift-package-guard-") as raw:
        work = Path(raw)
        staged = work / "candidate"
        try:
            shutil.copytree(candidate, staged, symlinks=True, copy_function=os.link)
        except OSError:
            if staged.exists():
                shutil.rmtree(staged)
            shutil.copytree(candidate, staged, symlinks=True)
        package = source_root(staged)
        _remove_non_bridge_sources(package)
        trace_environment = _module_trace_environment(package, work)
        probe = (
            "const j=require(process.env.JSCODESHIFT_PACKAGE);"
            "if(typeof j!=='function'||!j.template||typeof j.template.statement!=='function') process.exit(2);"
            "if(j('const x=1;').find(j.Identifier).size()!==1) process.exit(3);"
        )
        result = subprocess.run(
            ["node", "-e", probe],
            cwd=package,
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "JSCODESHIFT_PACKAGE": str(package), **trace_environment},
        )
        if result.returncode != 0:
            return False, "package-root guard probe failed"
        loaded, node_processes, native_processes = _trace_loaded_package_modules(work / "modules.jsonl", package)
        disallowed = sorted(loaded - ALLOWED_JS_BRIDGE_PATHS)
        if disallowed:
            return False, "package-root loaded non-bridge JavaScript: " + ", ".join(disallowed)
        if node_processes == 0:
            return False, "package-root module trace observed no Node process"
        if native_processes == 0:
            return False, "package-root module trace observed no compiled Rust process"
    return True, "package-root executes with only the explicit JS bridge"


def check_rust_legacy_engine_boundary(candidate: Path) -> tuple[bool, str]:
    retained = retained_legacy_engine_copies(candidate)
    if retained:
        return False, "retained copies of the public JS engine: " + ", ".join(sorted(retained)[:8])
    return True, "no exact public-engine copies remain in the submitted package"


def check_rust_core_collections_ownership(candidate: Path) -> tuple[bool, str]:
    """Probe core collections independently with non-bridge sources removed."""

    return ownership_probe(
        candidate,
        label="core collections",
        source_files={"project/collections.js": "const original = 1;\n"},
        transform_text=(
            "module.exports = (file, api) => { const j = api.jscodeshift; const root = j(file.source); "
            "if (root.find(j.Identifier,{name:'original'}).size() !== 1) throw new Error('collection find failed'); "
            "root.find(j.Identifier,{name:'original'}).replaceWith(() => j.identifier('collectionOwned')); "
            "return root.toSource(); };\n"
        ),
        marker="collectionOwned",
    )


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
        "rust-parser-babel-ownership": check_rust_parser_babel_ownership,
        "rust-parser-typescript-ownership": check_rust_parser_typescript_ownership,
        "rust-parser-tsx-ownership": check_rust_parser_tsx_ownership,
        "rust-printer-comments-ownership": check_rust_printer_comments_ownership,
        "rust-core-collections-ownership": check_rust_core_collections_ownership,
        "rust-core-builders-ownership": check_rust_core_builders_ownership,
        "rust-core-templates-ownership": check_rust_core_templates_ownership,
        "rust-core-nodepath-ownership": check_rust_core_nodepath_ownership,
        "rust-edge-ast-ownership": check_rust_edge_ast_ownership,
        "rust-edge-cli-ownership": check_rust_edge_cli_ownership,
        "rust-worker-multifile-ownership": check_rust_worker_multifile_ownership,
        "rust-worker-parallel-ownership": check_rust_worker_parallel_ownership,
        "rust-worker-failure-ownership": check_rust_worker_failure_ownership,
        "rust-worker-determinism-ownership": check_rust_worker_determinism_ownership,
        "rust-package-root-ownership": check_rust_package_root_ownership,
        "rust-package-clean-pack-ownership": check_rust_package_clean_pack_ownership,
        "rust-package-guard-ownership": check_rust_package_guard_ownership,
        "rust-legacy-engine-boundary": check_rust_legacy_engine_boundary,
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
