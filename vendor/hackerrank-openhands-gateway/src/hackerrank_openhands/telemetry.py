"""Small telemetry collector for the OpenHands JSONL event stream."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .harness import redact


_OUTCOME_EVENT_TYPES = {
    "ObservationEvent",
    "AgentErrorEvent",
    "UserRejectObservation",
}


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _usage(
    metrics: dict[str, Any],
    *,
    gateway_total_tokens: int | float | None = None,
) -> dict[str, int | float | None]:
    """Normalize token field names emitted by OpenHands and Gateway adapters."""
    input_tokens = _number(metrics.get("input_tokens", metrics.get("prompt_tokens")))
    output_tokens = _number(metrics.get("output_tokens", metrics.get("completion_tokens")))
    cache_read = _number(metrics.get("cache_read_input_tokens", metrics.get("cache_read_tokens")))
    cache_write = _number(metrics.get("cache_creation_input_tokens", metrics.get("cache_write_tokens")))
    cached = _number(metrics.get("cached_input_tokens"))
    if cached is None and (cache_read is not None or cache_write is not None):
        cached = (cache_read or 0) + (cache_write or 0)
    reasoning = _number(metrics.get("reasoning_tokens", metrics.get("reasoning_output_tokens")))
    # `prompt_tokens`/`input_tokens` already includes cache-read tokens in the
    # OpenAI/LiteLLM usage shape.  Adding `cached` here would count those tokens
    # twice. Prefer an explicitly reported total, then the Gateway aggregate,
    # and only then derive total usage from input plus output.
    total = _number(metrics.get("total_tokens"))
    if total is None:
        total = _number(gateway_total_tokens)
    if total is None and any(value is not None for value in (input_tokens, output_tokens)):
        total = (input_tokens or 0) + (output_tokens or 0)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    }


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duration_ms(start: str, end: str) -> int | None:
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0, int((end_dt - start_dt).total_seconds() * 1000))
    except (TypeError, ValueError):
        return None


def _gateway_cost(path: Path | None) -> tuple[float | None, int]:
    """Sum provider-reported Gateway costs from captured response records."""
    if path is None or not path.exists():
        return None, 0
    total = 0.0
    reported_responses = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("status") != "ok":
            continue
        response = record.get("response")
        usage = response.get("usage") if isinstance(response, dict) else None
        value = _number(usage.get("cost")) if isinstance(usage, dict) else None
        if value is not None:
            total += float(value)
            reported_responses += 1
    return (total if reported_responses else None), reported_responses


def _gateway_total_tokens(path: Path | None) -> int | float | None:
    """Return the complete Gateway-reported token total when available."""
    if path is None or not path.exists():
        return None

    total = 0
    response_count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("status") != "ok":
            continue
        response = record.get("response")
        usage = response.get("usage") if isinstance(response, dict) else None
        reported = _number(usage.get("total_tokens")) if isinstance(usage, dict) else None
        if reported is None:
            return None
        total += reported
        response_count += 1
    return total if response_count else None


def _gateway_latency(path: Path | None) -> dict[str, int | float | None]:
    """Summarize per-request Gateway latency captured by the harness."""
    summary: dict[str, int | float | None] = {
        "count": 0,
        "with_latency": 0,
        "successful": 0,
        "failed": 0,
        "total_latency_ms": 0.0,
        "average_latency_ms": None,
        "min_latency_ms": None,
        "max_latency_ms": None,
    }
    if path is None or not path.exists():
        return summary

    latencies: list[float] = []
    request_count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        request_count += 1
        if record.get("status") == "ok":
            summary["successful"] = int(summary["successful"] or 0) + 1
        elif record.get("status") == "error":
            summary["failed"] = int(summary["failed"] or 0) + 1
        latency = _number(record.get("latency_ms"))
        if latency is not None:
            latencies.append(float(latency))

    summary["count"] = request_count
    summary["with_latency"] = len(latencies)
    if latencies:
        summary["total_latency_ms"] = round(sum(latencies), 3)
        summary["average_latency_ms"] = round(sum(latencies) / len(latencies), 3)
        summary["min_latency_ms"] = min(latencies)
        summary["max_latency_ms"] = max(latencies)
    return summary


def _is_cancellation(record: dict[str, Any]) -> bool:
    """Identify OpenHands' synthetic cancellation error events."""
    error = str(record.get("error", "")).lower()
    return "cancel" in error or record.get("error_kind") == "cancelled"


def _outcome_status(record: dict[str, Any]) -> str:
    """Map a serialized OpenHands outcome event to a telemetry status."""
    event_type = record.get("event_type")
    if event_type == "UserRejectObservation":
        return "rejected"
    if event_type == "AgentErrorEvent":
        return "cancelled" if _is_cancellation(record) else "error"
    if event_type == "ObservationEvent":
        return "error" if record.get("observation_is_error") else "ok"
    return "unknown"


def _matches_action(action: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Match outcomes by exact SDK identifiers, with legacy fallback support."""
    action_id = action.get("event_id")
    candidate_action_id = candidate.get("action_id")
    if action_id and candidate_action_id:
        return action_id == candidate_action_id

    tool_call_id = action.get("tool_call_id")
    candidate_tool_call_id = candidate.get("tool_call_id")
    if tool_call_id and candidate_tool_call_id:
        return tool_call_id == candidate_tool_call_id

    # Preserve compatibility with older/synthetic event streams that predate
    # identifiers, while ensuring the fallback is never used for identified
    # events where it could pair the wrong repeated tool call.
    return (
        not action_id
        and not candidate_action_id
        and not tool_call_id
        and not candidate_tool_call_id
        and action.get("tool_name") == candidate.get("tool_name")
    )


def _outcome_metadata(outcome: dict[str, Any] | None) -> dict[str, Any]:
    """Copy safe outcome metadata onto the corresponding trajectory action."""
    if outcome is None:
        return {}
    fields = (
        "event_id",
        "error",
        "error_kind",
        "error_retryable",
        "observation_is_error",
        "rejection_source",
        "rejection_reason",
    )
    return {
        f"outcome_{field}": outcome[field]
        for field in fields
        if field in outcome
    }


def collect(
    events_path: Path,
    output_path: Path,
    *,
    model: str,
    reasoning: str,
    started_at: str,
    completed_at: str,
    status: str,
    exit_code: int,
    error: dict[str, str] | None = None,
    gateway_responses_path: Path | None = None,
    redact_output: bool | None = None,
) -> dict[str, Any]:
    """Convert one JSONL event file into telemetry and trajectory files."""
    records: list[dict[str, Any]] = []
    invalid = 0
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
                else:
                    invalid += 1
            except json.JSONDecodeError:
                invalid += 1

    metrics = next((record for record in reversed(records) if record.get("type") == "openhands_metrics"), {})
    workspace_metrics = next((record for record in reversed(records) if record.get("type") == "workspace_metrics"), None)
    actions = [
        (index, record)
        for index, record in enumerate(records)
        if record.get("type") == "openhands_event"
        and record.get("tool_name")
        # Older/synthetic event streams may omit event_type; treat those
        # tool-bearing records as actions while keeping observations excluded.
        and record.get("event_type") in (None, "ActionEvent")
    ]
    trajectory: list[dict[str, Any]] = []
    for index, record in actions:
        observation = next(
            (
                candidate
                for candidate in records[index + 1 :]
                if candidate.get("type") == "openhands_event"
                and candidate.get("event_type") in _OUTCOME_EVENT_TYPES
                and _matches_action(record, candidate)
            ),
            None,
        )
        trajectory.append({
            **record,
            "status": _outcome_status(observation) if observation else "unknown",
            "outcome_event_type": observation.get("event_type") if observation else None,
            **_outcome_metadata(observation),
        })
    by_tool: dict[str, int] = {}
    for record in trajectory:
        name = str(record["tool_name"])
        by_tool[name] = by_tool.get(name, 0) + 1
    raw_cost = _number(metrics.get("cost_usd"))
    # OpenHands reports 0.0 when LiteLLM has no pricing entry for a model. Do
    # not present that fallback as authoritative billing data.
    cost = raw_cost if raw_cost is not None and raw_cost > 0 else None
    gateway_cost, gateway_cost_responses = _gateway_cost(gateway_responses_path)
    gateway_total_tokens = _gateway_total_tokens(gateway_responses_path)
    gateway_latency = _gateway_latency(gateway_responses_path)
    successful = sum(record.get("status") == "ok" for record in trajectory)
    failed = sum(record.get("status") == "error" for record in trajectory)
    cancelled = sum(record.get("status") == "cancelled" for record in trajectory)
    rejected = sum(record.get("status") == "rejected" for record in trajectory)
    unknown = sum(record.get("status") == "unknown" for record in trajectory)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "harness": {"name": "hackerrank-openhands-gateway", "version": "0.1.0"},
        "run": {"status": status, "exit_code": exit_code, "error": redact(error, enabled=redact_output) if error else None},
        "model": {"name": model, "reasoning": reasoning, "provider": "hackerrank-gateway"},
        "timing": {
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": _duration_ms(started_at, completed_at),
            "llm_requests": gateway_latency,
        },
        "usage": _usage(metrics, gateway_total_tokens=gateway_total_tokens),
        "cost": {
            "gateway": {
                "amount_usd": gateway_cost,
                "currency": "USD",
                "status": "reported" if gateway_cost is not None else "unavailable",
                "source": "gateway",
                "responses_with_cost": gateway_cost_responses,
            },
            "openhands": {
                "amount_usd": cost,
                "currency": "USD",
                "status": "reported" if cost is not None else "unavailable",
                "source": "openhands",
            },
        },
        "workspace": redact(workspace_metrics, enabled=redact_output) if workspace_metrics else {"status": "unavailable", "reason": "workspace metrics event not found"},
        "tools": {"total": len(trajectory), "successful": successful, "failed": failed, "cancelled": cancelled, "rejected": rejected, "unknown": unknown, "by_tool": by_tool},
        "trace": {"events_path": events_path.name, "event_count": len(records), "invalid_event_count": invalid, "integrity_sha256": _sha256(events_path)},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output_path.parent / "trajectory.json").write_text(json.dumps(redact(trajectory, enabled=redact_output), indent=2) + "\n", encoding="utf-8")
    return manifest
