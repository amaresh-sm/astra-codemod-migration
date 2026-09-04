"""Collect comparable, privacy-safe telemetry for candidate-generation runs."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


EXCLUDED_DIRECTORIES = {".git", ".next", ".venv", "__pycache__", "coverage", "dist", "build", "node_modules", "target"}
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cs", ".css", ".go", ".html", ".java", ".jsx", ".kt", ".mjs", ".php", ".py", ".rb", ".rs", ".sh", ".sql", ".swift", ".ts", ".tsx", ".vue"}
TEST_MARKERS = ("/test/", "/tests/", "/__tests__/", ".test.", ".spec.")
TOOL_TYPES = ("read", "shell", "edit", "write", "other")


def _included_files(root: Path) -> list[Path]:
    """Return source files while excluding dependencies and generated output."""
    if not root.is_dir():
        return []
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in EXCLUDED_DIRECTORIES for part in path.relative_to(root).parts)
    ]


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_workspace(workspace: Path) -> dict[str, str]:
    """Capture public input files before the agent modifies its workspace."""
    snapshot: dict[str, str] = {}
    for path in _included_files(workspace):
        try:
            snapshot[str(path.relative_to(workspace))] = _digest(path)
        except OSError:
            continue
    return snapshot


def summarize_solution(workspace: Path, before: dict[str, str]) -> dict[str, object]:
    """Report total source size and the source files changed by the agent."""
    files = _included_files(workspace)
    source_files = [path for path in files if path.suffix.lower() in SOURCE_SUFFIXES]
    test_files = [path for path in source_files if any(marker in f"/{path.relative_to(workspace)}" for marker in TEST_MARKERS)]
    after: dict[str, str] = {}
    for path in files:
        try:
            after[str(path.relative_to(workspace))] = _digest(path)
        except OSError:
            continue
    changed = set(before).symmetric_difference(after) | {key for key in before.keys() & after.keys() if before[key] != after[key]}
    changed_source = [path for path in source_files if str(path.relative_to(workspace)) in changed]
    return {
        "workspace_source_files": len(source_files),
        "workspace_source_lines": sum(_line_count(path) for path in source_files),
        "workspace_test_files": len(test_files),
        "workspace_test_lines": sum(_line_count(path) for path in test_files),
        "agent_changed_files": len(changed),
        "agent_changed_source_files": len(changed_source),
        "agent_changed_source_lines": sum(_line_count(path) for path in changed_source),
    }


def parse_tokens(log_path: Path) -> dict[str, object]:
    """Extract provider-reported usage where it is present in an agent log."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"input": None, "output": None, "cached_input": None, "total": None, "source": "unavailable"}

    for line in reversed(text.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = event.get("usage") if isinstance(event, dict) else None
        if not isinstance(usage, dict):
            continue
        if "input_tokens" not in usage and "output_tokens" not in usage:
            continue
        cached = int(usage.get("cache_creation_input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
        input_tokens = int(usage.get("input_tokens") or 0) + cached
        output_tokens = int(usage.get("output_tokens") or 0)
        return {"input": input_tokens, "output": output_tokens, "cached_input": cached, "total": input_tokens + output_tokens, "source": "provider-reported"}

    def find(pattern: str) -> int | None:
        match = re.search(pattern, text, re.IGNORECASE)
        return int(match.group(1).replace(",", "")) if match else None

    input_tokens = find(r"input[ _]tokens?\D+(\d[\d,]*)")
    output_tokens = find(r"output[ _]tokens?\D+(\d[\d,]*)")
    total = find(r"total[ _]tokens?\D+(\d[\d,]*)") or find(r"tokens?\s+used\D+(\d[\d,]*)")
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    source = "agent-log" if total is not None or input_tokens is not None or output_tokens is not None else "unavailable"
    return {"input": input_tokens, "output": output_tokens, "cached_input": None, "total": total, "source": source}


def parse_tool_calls(log_path: Path) -> dict[str, object]:
    """Count structured tool-use events without pretending plain logs are complete."""
    counts: Counter[str] = Counter()
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for tool_name in _event_tool_names(event):
            counts[_classify_tool(tool_name)] += 1
    total = sum(counts.values())
    return {
        "total": total if total else None,
        "by_type": {tool_type: counts.get(tool_type, 0) if total else None for tool_type in TOOL_TYPES},
        "source": "agent-event-log" if total else "unavailable",
    }


def _event_tool_names(event: object) -> list[str]:
    """Recognize Codex, Claude Code, and OpenAI-compatible structured events."""
    if not isinstance(event, dict):
        return []
    item = event.get("item")
    if isinstance(item, dict) and isinstance(item.get("type"), str):
        item_type = item["type"]
        if item_type in {"command_execution", "file_change", "mcp_tool_call"}:
            return [item_type]
    names: list[str] = []
    content = event.get("content")
    message = event.get("message")
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in {"tool_use", "tool_call", "function_call"}:
                names.append(str(block.get("name") or block.get("type")))
    event_type = event.get("type")
    if event_type in {"tool_use", "tool_call", "function_call"}:
        names.append(str(event.get("name") or event_type))
    return names


def _classify_tool(tool_name: str) -> str:
    """Map provider-specific tool names to stable benchmark categories."""
    normalized = tool_name.lower()
    if normalized == "command_execution" or any(part in normalized for part in ("bash", "shell", "command", "terminal")):
        return "shell"
    if normalized == "file_change" or any(part in normalized for part in ("apply_patch", "edit", "write")):
        return "edit"
    if any(part in normalized for part in ("read", "view", "search", "grep", "find")):
        return "read"
    return "other"


def collect(workspace: Path, before: dict[str, str], log_path: Path) -> dict[str, object]:
    """Build the telemetry document persisted beside generation metadata."""
    return {"schema_version": 1, "tokens": parse_tokens(log_path), "tool_calls": parse_tool_calls(log_path), "solution_size": summarize_solution(workspace, before)}
