"""Run black-box migration checks against the submitted CLI."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from jscodeshift_checks import CRITERIA, SCENARIO_IDS, check as genuine_check


def code_root(candidate: Path) -> Path:
    """Resolve either a flat reference layout or the public ``codebase/`` layout."""
    nested = candidate / "codebase"
    return nested if nested.is_dir() and not (candidate / "bin").is_dir() else candidate


def invoke(candidate: Path, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    source_root = code_root(candidate)
    return subprocess.run(
        ["node", str(source_root / "bin/codemod-plan.js"), "--root", str(root), *extra],
        cwd=source_root, text=True, capture_output=True, check=False,
    )


def check(candidate: Path) -> dict[str, str]:
    root = Path(tempfile.mkdtemp(prefix="planner-verifier-"))
    outside = Path(tempfile.mkdtemp(prefix="planner-outside-"))
    try:
        (root / "src").mkdir(parents=True)
        (root / "node_modules/pkg").mkdir(parents=True)
        (root / "dist").mkdir()
        (root / "generated").mkdir()
        (root / "src/z.ts").write_text("export const z = 1;", encoding="utf-8")
        (root / "src/a.js").write_text("export const a = 1;", encoding="utf-8")
        (root / "generated/keep.js").write_text("generated", encoding="utf-8")
        (root / "node_modules/pkg/index.js").write_text("ignored", encoding="utf-8")
        (root / "dist/out.js").write_text("ignored", encoding="utf-8")
        (outside / "escape.js").write_text("outside", encoding="utf-8")
        (root / "safe-link.js").symlink_to(root / "src/a.js")
        (root / "escape-link.js").symlink_to(outside / "escape.js")

        statuses: dict[str, str] = {}
        result = invoke(candidate, root, "--extensions", "js,ts")
        payload = {}
        try:
            payload = json.loads(result.stdout)
            ok = result.returncode == 0 and payload == {
                "files": ["generated/keep.js", "safe-link.js", "src/a.js", "src/z.ts"],
                "count": 4,
            }
        except (json.JSONDecodeError, TypeError):
            ok = False
        statuses["cli-contract"] = "pass" if ok else "fail"

        statuses["deterministic-discovery"] = "pass" if ok and payload.get("files") == sorted(payload.get("files", [])) else "fail"
        custom = invoke(candidate, root, "--extensions", "js", "--ignore", "generated")
        try:
            custom_payload = json.loads(custom.stdout)
            ignore_ok = custom.returncode == 0 and custom_payload["files"] == ["safe-link.js", "src/a.js"]
        except (json.JSONDecodeError, TypeError, KeyError):
            ignore_ok = False
        statuses["ignore-rules"] = "pass" if ignore_ok else "fail"
        statuses["symlink-boundary"] = "pass" if ok and "escape-link.js" not in payload.get("files", []) and "safe-link.js" in payload.get("files", []) else "fail"
        source_root = code_root(candidate)
        bridge = source_root / "src/planner.js"
        native = next(
            (
                source_root / relative
                for relative in (
                    "native/planner/Cargo.toml",
                    "rust-planner/Cargo.toml",
                    "rust/Cargo.toml",
                )
                if (source_root / relative).is_file()
            ),
            None,
        )
        bridge_text = bridge.read_text(encoding="utf-8")
        statuses["rust-bridge"] = "pass" if native is not None and "spawnSync(plannerBinary(), args" in bridge_text else "fail"
        empty = invoke(candidate, root, "--extensions", "rs")
        missing = invoke(candidate, root / "missing", "--extensions", "js")
        try:
            empty_payload = json.loads(empty.stdout)
            empty_ok = empty.returncode == 0 and empty_payload == {"files": [], "count": 0} and missing.returncode != 0 and not missing.stdout.strip()
        except (json.JSONDecodeError, TypeError):
            empty_ok = False
        statuses["empty-and-error-cases"] = "pass" if empty_ok else "fail"
        return statuses
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--external-lifecycle", action="store_true")
    args = parser.parse_args()
    statuses = genuine_check(args.candidate.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    passed = all(value["status"] == "pass" for value in statuses.values())
    report = {
        "criterionStatus": {
            key: {"status": value["status"], "scenarioId": SCENARIO_IDS[key], "detail": value["detail"]}
            for key, value in statuses.items()
        },
        "status": "pass" if passed else "fail",
    }
    backend = args.output / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    (backend / "reward.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.output / "criteria.json").write_text(json.dumps({"criteria": statuses}, indent=2) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
