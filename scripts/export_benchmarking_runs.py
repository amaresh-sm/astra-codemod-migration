#!/usr/bin/env python3
"""Export scored candidate metadata and sanitized run evidence."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "benchmarking-candidates"
REGISTRY = ROOT / "scores.json"
DEST_ROOT = ROOT / "benchmarking-runs"

SECRET_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[^\s,;\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|secret|password)\s*[=:]\s*)[^,;\s}\]]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(ASTRA_GATEWAY_API_KEY|LLM_API_KEY|OPENAI_API_KEY)\s*=\s*[^\s]+"), r"\1=[REDACTED]"),
]


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        for pattern, replacement in SECRET_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    return value


def resolve_source(name: str) -> Path:
    direct = SOURCE_ROOT / name
    if direct.is_dir():
        return direct
    prefixed = SOURCE_ROOT / f"openhands-{name}"
    if prefixed.is_dir():
        return prefixed
    raise FileNotFoundError(f"No candidate artifact for {name}")


def load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scrub(value), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def newest_score_report(source: Path) -> Path | None:
    reports = [p for p in source.rglob("reports/score.json") if p.is_file()]
    return max(reports, key=lambda p: p.stat().st_mtime) if reports else None


def source_json(source: Path, relative: str, fallback: Any) -> Any:
    value = load_json(source / relative)
    return fallback if value is None else value


def event_summary(source: Path) -> dict[str, Any]:
    event_file = source / "events.jsonl"
    if not event_file.is_file():
        return {"event_count": 0, "invalid_event_count": 0, "cost_usd": 0, "tool_trajectory": [], "capture": "not_captured"}
    invalid = 0
    events: list[dict[str, Any]] = []
    for line in event_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            invalid += 1
            continue
        if not isinstance(item, dict):
            continue
        event_type = item.get("type") or item.get("event_type") or item.get("kind") or "event"
        name = item.get("tool_name") or item.get("name") or item.get("action")
        timestamp = item.get("timestamp") or item.get("created_at") or item.get("time")
        entry: dict[str, Any] = {"sequence": len(events) + 1, "event_type": event_type}
        if timestamp is not None:
            entry["timestamp"] = timestamp
        if name is not None:
            entry["tool"] = name
        if "status" in item:
            entry["status"] = item["status"]
        if "success" in item:
            entry["success"] = item["success"]
        events.append(scrub(entry))
    return {"event_count": len(events), "invalid_event_count": invalid, "cost_usd": 0, "tool_trajectory": events}


def copy_sanitized_json(source_file: Path, destination: Path, fallback: Any) -> None:
    value = load_json(source_file) if source_file.is_file() else None
    write_json(destination, fallback if value is None else value)


def write_sanitized_jsonl(source_file: Path, destination: Path, run_id: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as out:
        if not source_file.is_file():
            out.write(json.dumps({"type": "capture_status", "status": "not_captured", "run": run_id}) + "\n")
            return
        for line in source_file.read_text(encoding="utf-8", errors="replace").splitlines():
            out.write(scrub(line) + "\n")


def verifier_log(source: Path, score_report: Path | None, score: float) -> str:
    lines = [
        "Benchmark scoring evidence",
        f"source_candidate={source.name}",
        f"registry_score={score:.10f}",
        f"score_report={score_report.relative_to(source) if score_report else 'not_captured'}",
        "",
    ]
    log_dirs = [p for p in source.iterdir() if p.is_dir() and p.name.startswith(("verification", "rescore"))]
    if log_dirs:
        latest = max(log_dirs, key=lambda p: p.stat().st_mtime)
        lines.append(f"verification_directory={latest.name}")
        for name in ("candidate.build.log", "candidate.rebuild.log", "candidate.reset.log", "candidate.start.log", "verifier.stdout.log", "verifier.stderr.log"):
            path = latest / "logs" / name
            if path.is_file():
                lines.append(f"\n--- {name} ---\n{path.read_text(encoding='utf-8', errors='replace')}")
    else:
        lines.append("No verifier log directory was captured for this run.")
    return scrub("\n".join(lines))


def main() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    export_time = datetime.now(timezone.utc).isoformat()
    if DEST_ROOT.exists():
        shutil.rmtree(DEST_ROOT)
    (DEST_ROOT / "runs").mkdir(parents=True)
    manifest: list[dict[str, Any]] = []

    for group in registry["groups"]:
        model = group["model"]
        reasoning = group["reasoning"]
        for score, run_name in zip(group["scores"], group["candidates"]):
            source = resolve_source(run_name)
            score = float(score)
            score_report = newest_score_report(source)
            if score_report is None:
                raise RuntimeError(f"Missing score report for {run_name}")
            report = load_json(score_report) or {}
            reported_score = report.get("score")
            if reported_score is None or abs(float(reported_score) - score) > 0.00011:
                raise RuntimeError(f"Score mismatch for {run_name}: registry={score}, report={reported_score}")

            target = DEST_ROOT / "runs" / model / reasoning / run_name
            target.mkdir(parents=True, exist_ok=True)
            source_metadata = source_json(source, "metadata.json", {})
            metadata = source_metadata if isinstance(source_metadata, dict) else {}
            metadata["benchmarking"] = {
                "schema_version": 1,
                "task": "migrate-jscodeshift-runner-to-rust",
                "run_name": run_name,
                "model": model,
                "reasoning": reasoning,
                "score": score,
                "score_source": "scores.json and newest reports/score.json",
                "source_candidate": source.name,
                "exported_at": export_time,
            }
            write_json(target / "metadata.json", metadata)

            telemetry = source_json(source, "telemetry.json", {
                "schema_version": 1,
                "harness": {"name": "hackerrank-openhands-gateway"},
                "run": {"id": run_name, "status": "captured_without_telemetry"},
                "model": {"name": model, "reasoning": reasoning},
                "benchmarking": {"score": score, "source": "scores.json"},
            })
            if isinstance(telemetry, dict):
                telemetry["benchmarking"] = {"score": score, "source": "scores.json", "run_name": run_name}
            write_json(target / "telemetry" / "openhands-telemetry.json", telemetry)

            trajectory = source / "trajectory.json"
            copy_sanitized_json(trajectory, target / "trajectory" / "openhands-trajectory.json", {
                "schema_version": 1, "capture": "not_captured", "run": run_name,
            })
            write_json(target / "logs" / "events.sanitized.json", event_summary(source))
            write_sanitized_jsonl(source / "gateway_responses.jsonl", target / "logs" / "openhands-gateway_responses.jsonl", run_name)
            (target / "logs" / "hidden-scorer.log").write_text(
                verifier_log(source, score_report, score), encoding="utf-8"
            )
            score_copy = scrub(report)
            score_copy["benchmarking_registry_score"] = score
            write_json(target / "score" / "hidden.score.json", score_copy)
            manifest.append({"model": model, "reasoning": reasoning, "run_name": run_name, "source": source.name, "score": score})

    write_json(DEST_ROOT / "manifest.json", {"schema_version": 1, "source": "scores.json", "generated_at": export_time, "runs": manifest})
    (DEST_ROOT / "README.md").write_text(
        "# Benchmarking run evidence\n\n"
        "This directory stores scored-run metadata and sanitized evidence for the migration benchmark. "
        "The authoritative score registry is the repository root `scores.json`; each exported score was "
        "checked against the newest `reports/score.json` in its source artifact. Candidate source trees, "
        "dependencies, caches, and credentials are intentionally excluded. Missing Pi/OpenHands captures "
        "are represented honestly with `capture: not_captured` placeholders.\n\n"
        f"Exported runs: {len(manifest)}\n",
        encoding="utf-8",
    )
    print(f"exported {len(manifest)} runs to {DEST_ROOT}")


if __name__ == "__main__":
    main()
