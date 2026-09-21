#!/usr/bin/env python3
"""Regenerate benchmarking-data.md from scores, telemetry, and retained run logs."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "benchmarking-data.md"
MANIFEST_FILE = ROOT / "benchmarking-runs" / "manifest.json"
RUNS_ROOT = ROOT / "benchmarking-runs" / "runs"
SOURCE_ROOT = ROOT / "benchmarking-candidates"
PRICING_SRC = ROOT / "vendor" / "hackerrank-openhands-gateway" / "src"
sys.path.insert(0, str(PRICING_SRC))
from hackerrank_openhands.pricing import (  # noqa: E402
    PRICING_TABLE,
    normalize_model_name,
    normalize_usage,
)


HEADER = "| Run-name (unique Id) | Model Name | Reasoning | score | Token (input/output/reasoning/cache-read) | tool calls | Iteration steps | Est cost | Reported cost | Duration | Total Files | Loc | deps | largest file |"
ALIGNMENT = "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"

CORE_SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".css", ".go", ".html", ".java", ".js", ".jsx",
    ".kt", ".mjs", ".php", ".py", ".rb", ".rs", ".sh", ".sql", ".swift",
    ".ts", ".tsx", ".vue",
}
EXCLUDED_SOURCE_DIRECTORIES = {
    ".cargo", ".cargo-home", ".git", ".next", ".verify", ".venv", "app-setup",
    "build", "cache", "coverage", "dist", "generated", "logs", "node_modules",
    "target", "tmp", "vendor",
}
EXCLUDED_SOURCE_NAMES = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
    "pnpm-lock.yaml", "cargo.lock", "composer.lock",
}
EXCLUDED_SOURCE_PARTS = (
    "dump", "backup", "snapshot", "cache", "lockfile",
)


def parse_row(line: str) -> list[str]:
    return [part.strip() for part in line.split("|")[1:-1]]


def format_int(value: Any) -> str:
    return f"{int(value):,}" if value is not None else "—"


def compact_token_count(value: Any) -> str:
    if value is None:
        return "—"
    value = int(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def format_tokens(usage: dict[str, Any]) -> str:
    normalized = normalize_usage(usage or {})
    if normalized is None:
        return "—"
    return (
        f"{compact_token_count(normalized.get('input_tokens'))}/"
        f"{compact_token_count(normalized.get('output_tokens'))}/"
        f"{compact_token_count(normalized.get('reasoning_tokens'))}/"
        f"{compact_token_count(normalized.get('cache_read_tokens'))}"
    )


def estimated_cost(model: str, usage: dict[str, Any]) -> float | None:
    spec = PRICING_TABLE.get(normalize_model_name(model))
    normalized = normalize_usage(usage or {})
    if spec is None or normalized is None:
        return None
    input_tokens = int(normalized["input_tokens"])
    output_tokens = int(normalized["output_tokens"])
    cache_read = int(normalized["cache_read_tokens"])
    cache_write = int(normalized["cache_write_tokens"])
    input_rate, output_rate, cache_read_rate, cache_write_rate = spec.rates_for_input(input_tokens)
    uncached = input_tokens - cache_read - cache_write
    total = (
        uncached * input_rate
        + cache_read * (cache_read_rate if cache_read_rate is not None else input_rate)
        + cache_write * (cache_write_rate if cache_write_rate is not None else input_rate)
        + output_tokens * output_rate
    ) / 1_000_000
    return total


def reported_cost(telemetry: dict[str, Any]) -> float | None:
    costs = telemetry.get("cost", {})
    for section in ("gateway", "openhands"):
        value = costs.get(section, {}).get("amount_usd")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def telemetry_for(manifest_item: dict[str, Any]) -> dict[str, Any]:
    path = RUNS_ROOT / manifest_item["model"] / manifest_item["reasoning"] / manifest_item["run_name"] / "telemetry" / "openhands-telemetry.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def candidate_source_root(run_name: str) -> Path | None:
    """Locate the retained candidate codebase used for source-size metadata."""
    source = SOURCE_ROOT / run_name
    if not source.is_dir():
        source = SOURCE_ROOT / f"openhands-{run_name}"
    codebase = source / "candidate" / "codebase"
    if codebase.is_dir():
        return codebase
    candidate = source / "candidate"
    return candidate if candidate.is_dir() else None


def candidate_artifact_root(run_name: str) -> Path | None:
    source = SOURCE_ROOT / run_name
    if not source.is_dir():
        source = SOURCE_ROOT / f"openhands-{run_name}"
    return source if source.is_dir() else None


def pi_artifact_root(run_name: str) -> Path | None:
    """Locate a retained host-side Pi session for a Pi run."""
    if not run_name.startswith("pi-"):
        return None
    slug = re.sub(r"^pi-([^-]+)-5-", r"pi-\1-", run_name)
    slug = re.sub(r"-native-repair-.*$", "", slug)
    candidates = [Path("/private/tmp") / ("astra-" + slug)]
    if re.search(r"-r\d+$", slug):
        candidates.append(Path("/private/tmp") / re.sub(r"-r\d+$", "", "astra-" + slug))
    return next((path for path in candidates if path.is_dir()), None)


def pi_session_usage(run_name: str) -> dict[str, Any] | None:
    root = pi_artifact_root(run_name)
    if root is None:
        return None
    sessions = sorted((root / "session").glob("*.jsonl"))
    if not sessions:
        return None
    totals = {key: 0 for key in ("input_tokens", "output_tokens", "reasoning_tokens", "total_tokens", "cached_input_tokens", "cache_read_tokens", "cache_write_tokens")}
    usable = 0
    for line in sessions[0].read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = record.get("message") or {}
        usage = message.get("usage") if message.get("role") == "assistant" else None
        if not isinstance(usage, dict):
            continue
        usable += 1
        cache_read = int(usage.get("cacheRead") or 0)
        cache_write = int(usage.get("cacheWrite") or 0)
        totals["input_tokens"] += int(usage.get("input") or 0) + cache_read + cache_write
        totals["output_tokens"] += int(usage.get("output") or 0)
        totals["reasoning_tokens"] += int(usage.get("reasoning") or 0)
        totals["total_tokens"] += int(usage.get("totalTokens") or 0)
        totals["cached_input_tokens"] += cache_read + cache_write
        totals["cache_read_tokens"] += cache_read
        totals["cache_write_tokens"] += cache_write
    return totals if usable else None


def pi_event_counts(run_name: str) -> tuple[int | None, int | None]:
    root = pi_artifact_root(run_name)
    if root is None:
        return None, None
    sessions = sorted((root / "session").glob("*.jsonl"))
    if not sessions:
        return None, None
    tool_calls = 0
    for line in sessions[0].read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = record.get("message") or {}
        if message.get("role") != "assistant":
            continue
        tool_calls += sum(1 for block in message.get("content", []) if isinstance(block, dict) and block.get("type") == "toolCall")
    turns = 0
    event_log = root / "output" / "pi-events.jsonl"
    if event_log.is_file():
        for line in event_log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                if json.loads(line).get("type") == "turn_end":
                    turns += 1
            except json.JSONDecodeError:
                continue
    return tool_calls, turns or None


def pi_duration(run_name: str) -> str | None:
    root = pi_artifact_root(run_name)
    if root is None:
        return None
    sessions = sorted((root / "session").glob("*.jsonl"))
    if not sessions:
        return None
    timestamps: list[datetime] = []
    for line in sessions[0].read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line).get("timestamp")
            if isinstance(value, str):
                timestamps.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    if len(timestamps) < 2:
        return None
    total_seconds = max(0, int((max(timestamps) - min(timestamps)).total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes:02d}m {seconds:02d}s" if hours else f"{minutes}m {seconds:02d}s"


def candidate_json(run_name: str, *relative_paths: str) -> dict[str, Any]:
    root = candidate_artifact_root(run_name)
    if root is None:
        return {}
    for relative in relative_paths:
        path = root / relative
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return {}


def normalized_candidate_usage(run_name: str) -> dict[str, Any] | None:
    """Recover usage from retained nested telemetry or gateway responses."""
    for telemetry in (
        candidate_json(run_name, "telemetry.json"),
        candidate_json(run_name, ".openhands-output/telemetry.json"),
    ):
        usage = normalize_usage(telemetry.get("usage", {}))
        if usage is not None:
            return usage
    usage = pi_session_usage(run_name)
    if usage is not None:
        return usage

    root = candidate_artifact_root(run_name)
    if root is None:
        return None
    response_paths = [root / "gateway_responses.jsonl", root / ".openhands-output" / "gateway_responses.jsonl"]
    response_path = next((path for path in response_paths if path.is_file()), None)
    if response_path is None:
        return None

    totals = {key: 0 for key in ("input_tokens", "output_tokens", "reasoning_tokens", "total_tokens", "cached_input_tokens", "cache_read_tokens", "cache_write_tokens")}
    usable = 0
    for line in response_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("status") != "ok":
            continue
        usage = normalize_usage((record.get("response") or {}).get("usage") or {})
        if usage is None:
            continue
        usable += 1
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
    return totals if usable else None


def candidate_reported_cost(run_name: str) -> float | None:
    """Use a complete per-response gateway cost total as a last resort."""
    root = candidate_artifact_root(run_name)
    if root is None:
        return None
    response_paths = [root / "gateway_responses.jsonl", root / ".openhands-output" / "gateway_responses.jsonl"]
    response_path = next((path for path in response_paths if path.is_file()), None)
    if response_path is None:
        return None
    costs: list[float] = []
    successful = 0
    for line in response_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("status") != "ok":
            continue
        successful += 1
        value = ((record.get("response") or {}).get("usage") or {}).get("cost")
        if not isinstance(value, (int, float)):
            return None
        costs.append(float(value))
    return sum(costs) if successful and len(costs) == successful else None


def candidate_event_counts(run_name: str) -> tuple[int | None, int | None]:
    root = candidate_artifact_root(run_name)
    if root is None:
        return pi_event_counts(run_name)
    paths = [root / "events.jsonl", root / ".openhands-output" / "events.jsonl"]
    path = next((candidate for candidate in paths if candidate.is_file()), None)
    if path is None:
        return pi_event_counts(run_name)
    actions = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event_type") == "ActionEvent":
            actions += 1
    return actions, actions


def candidate_duration(run_name: str) -> str | None:
    for telemetry in (
        candidate_json(run_name, "telemetry.json"),
        candidate_json(run_name, ".openhands-output/telemetry.json"),
    ):
        duration_ms = (telemetry.get("timing") or {}).get("duration_ms")
        if isinstance(duration_ms, (int, float)):
            total_seconds = max(0, int(round(duration_ms / 1000)))
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours}h {minutes:02d}m {seconds:02d}s" if hours else f"{minutes}m {seconds:02d}s"
    return pi_duration(run_name)


def is_core_source_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    parts = {part.lower() for part in relative.parts[:-1]}
    name = path.name.lower()
    if path.suffix.lower() not in CORE_SOURCE_SUFFIXES:
        return False
    if parts.intersection(EXCLUDED_SOURCE_DIRECTORIES):
        return False
    if name in EXCLUDED_SOURCE_NAMES:
        return False
    if any(part in EXCLUDED_SOURCE_PARTS for part in relative.parts):
        return False
    try:
        sample = path.read_bytes()[:8192]
    except OSError:
        return False
    return b"\x00" not in sample


def largest_core_file(run_name: str) -> str:
    """Return the largest first-party source file by physical LOC.

    Dependency trees, generated output, caches, lock/package metadata, logs,
    and dump-like files are deliberately excluded so this describes the task's
    implementation rather than the surrounding build environment.
    """
    root = candidate_source_root(run_name)
    if root is None:
        return "—"
    candidates: list[tuple[int, str]] = []
    for path in root.rglob("*"):
        if not path.is_file() or not is_core_source_file(path, root):
            continue
        try:
            line_count = len(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            continue
        candidates.append((line_count, str(path.relative_to(root))))
    if not candidates:
        return "—"
    lines, relative = max(candidates, key=lambda item: (item[0], item[1]))
    return f"{relative} ({lines:,} LOC)"


def main() -> None:
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    old_lines = DATA_FILE.read_text(encoding="utf-8").splitlines()
    old_rows = {}
    for line in old_lines:
        if line.startswith("| ") and not line.startswith("|---"):
            row = parse_row(line)
            if len(row) == 14 and row[0] not in {"Run-name (unique Id)", "Run-name (unique ID)"}:
                old_rows[row[0]] = row

    output_rows: list[list[str]] = []
    missing_metadata: list[str] = []
    for item in manifest["runs"]:
        run_name = item["run_name"]
        display_name = run_name if run_name.startswith("pi-") else f"openhands-{run_name}"
        row = list(old_rows.get(display_name, [display_name, item["model"], item["reasoning"], f"{item['score']:.4f}", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—"]))
        telemetry = telemetry_for(item)
        usage = telemetry.get("usage", {})
        if normalize_usage(usage) is None:
            usage = normalized_candidate_usage(run_name) or {}
        row[0] = display_name
        row[1] = item["model"]
        row[2] = item["reasoning"]
        row[3] = f"{float(item['score']):.4f}"
        row[4] = format_tokens(usage)
        estimate = estimated_cost(item["model"], usage)
        reported = reported_cost(telemetry)
        if reported is None:
            reported = candidate_reported_cost(run_name)
        row[7] = f"${estimate:.4f}" if estimate is not None else "—"
        row[8] = f"${reported:.4f}" if reported is not None else "—"
        event_tools, event_iterations = candidate_event_counts(run_name)
        if row[5] in {"—", "0"} and event_tools is not None:
            row[5] = str(event_tools)
        if row[6] in {"—", "0"} and event_iterations is not None:
            row[6] = str(event_iterations)
        if row[9] == "—":
            duration = candidate_duration(run_name)
            if duration is not None:
                row[9] = duration
        row[13] = largest_core_file(run_name)
        if not old_rows.get(display_name):
            missing_metadata.append(display_name)
        output_rows.append(row)

    lines = [
        "# Benchmarking data",
        "",
        "Generated from `scores.json`, `benchmarking-runs/manifest.json`, current telemetry, and retained run logs when the exported summary is incomplete. "
        "Estimated cost uses uncached input, cache-read, cache-write, and output tokens with the vendored gateway pricing table. "
        "The token column is formatted as `input/output/reasoning/cache-read` with compact K/M units. "
        "Largest file is the highest-LOC first-party source file; dependencies, generated output, caches, logs, lock/package metadata, and dumps are excluded. "
        "Reported cost is the Gateway amount when available, otherwise the OpenHands amount. "
        "Runs that failed before model execution retain — for tokens, calls, steps, and estimated cost because no gateway request occurred; — otherwise means the source did not provide that field.",
        "",
        HEADER,
        ALIGNMENT,
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in output_rows)
    lines += ["", f"Rows: {len(output_rows)} scored candidate runs."]
    DATA_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if missing_metadata:
        print(f"warning: {len(missing_metadata)} runs had no previous descriptive row", file=sys.stderr)
    print(f"updated {DATA_FILE} with {len(output_rows)} runs")


if __name__ == "__main__":
    main()
