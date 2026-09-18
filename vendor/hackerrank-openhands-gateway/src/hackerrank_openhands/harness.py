"""Small, task-agnostic OpenHands + HackerRank Gateway wrapper."""

from __future__ import annotations

import asyncio
import json
import hashlib
import os
import re
import time
import warnings
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import SecretStr

from .workspace_metrics import compare_snapshots, snapshot_workspace


DEFAULT_GATEWAY_URL = "https://gateway-central.ai.private.hackerrank.link/v1"
REASONING_OPTIONS = ("none", "minimal", "low", "medium", "high", "xhigh", "ultra", "max")
_GATEWAY_RESPONSE_MAX_BYTES = 2 * 1024 * 1024
_GATEWAY_ERROR_BODY_MAX_CHARS = 4096
_gateway_response_path: ContextVar[Path | None] = ContextVar("gateway_response_path", default=None)
_redaction_enabled: ContextVar[bool] = ContextVar("redaction_enabled", default=True)


# Real upstream context windows (tokens) for gateway-routed models. LiteLLM has no
# built-in entry for these custom aliases, so without this it cannot tell OpenHands's
# condenser when a model is actually close to overflowing -- the agent just keeps
# growing history until the provider hard-rejects the request and the whole run is
# lost. Only add a model here once its real limit is confirmed; an unlisted model
# falls back to whatever (if anything) LiteLLM/OpenHands can resolve on their own.
GATEWAY_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "minimax-m3": 524_288,  # confirmed via a context_length_exceeded rejection at 1,114,695 tokens
}

# Condensation must kick in well before the hard limit: OpenHands's own token count is
# an estimate, the model's real output tokens still need to fit in what's left, and we
# want headroom before the provider's own rejection, not right up against it.
_CONTEXT_WINDOW_SAFETY_FACTOR = 0.8

# Every model gets a cap, not just the ones with a confirmed real limit. This one is
# deliberately conservative rather than accurate: it does not claim to match any
# specific model's real context window (unlike GATEWAY_MODEL_CONTEXT_WINDOWS above,
# which only ever holds confirmed numbers). It exists purely to keep every
# conversation bounded in size -- smaller, cheaper turns and less exposure to
# whatever makes a model slow or unreliable to respond on an unusually large request
# -- for every model we have not separately confirmed a real limit for. Confirmed
# data always wins over this guess: a model in GATEWAY_MODEL_CONTEXT_WINDOWS keeps
# its own (typically larger, since it is measured rather than assumed) safety margin.
_DEFAULT_CONSERVATIVE_MAX_INPUT_TOKENS = 120_000


def gateway_model_max_input_tokens(model: str) -> int:
    """Return the input-token cap to condense a gateway model's history against.

    A confirmed model (``GATEWAY_MODEL_CONTEXT_WINDOWS``) uses a safety margin below
    its real limit. Every other model still gets a bound: a conservative default
    that keeps history small regardless of the model's actual (unconfirmed) ceiling.
    """
    bare_model = model.removeprefix("openai/")
    window = GATEWAY_MODEL_CONTEXT_WINDOWS.get(bare_model)
    if window is not None:
        return int(window * _CONTEXT_WINDOW_SAFETY_FACTOR)
    return _DEFAULT_CONSERVATIVE_MAX_INPUT_TOKENS


def normalize_gateway_model(model: str) -> str:
    """Return the model string LiteLLM needs for its own client-side routing.

    This prefix (``openai/...``) only tells LiteLLM which provider adapter to
    use locally; LiteLLM strips it before serializing the request, so the
    wire body's ``model`` field is always the bare alias regardless. Passing
    a bare model here (no provider prefix) makes LiteLLM reject the call
    client-side with "LLM Provider NOT provided" before it ever reaches the
    network -- confirmed by reproducing that exact failure for minimax-m3.
    """
    return model if "/" in model else f"openai/{model}"


def now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact(value: Any, *, enabled: bool | None = None) -> Any:
    """Remove likely credentials from JSON-compatible telemetry values."""
    if enabled is None:
        enabled = _redaction_enabled.get()
    sensitive = ("authorization", "cookie", "credential", "password", "secret", "api_key", "apikey", "token")
    safe_telemetry_keys = {
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "cache_write_input_tokens",
        "reasoning_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
        "cached_tokens",
        "cache_write_tokens",
        "cache_creation_tokens",
        "audio_tokens",
        "image_tokens",
        "video_tokens",
        "accepted_prediction_tokens",
        "rejected_prediction_tokens",
        "cost",
        "cost_details",
        "upstream_inference_cost",
        "upstream_inference_prompt_cost",
        "upstream_inference_completions_cost",
    }
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if enabled and str(key) not in safe_telemetry_keys and any(part in str(key).lower() for part in sensitive) else redact(item, enabled=enabled)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, enabled=enabled) for item in value]
    if enabled and isinstance(value, str) and value.lower().startswith("bearer "):
        return "[REDACTED]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _event_record(event: Any) -> dict[str, Any]:
    """Serialize an OpenHands event with its structured payload.

    OpenHands represents actions, observations, errors, rejections, and
    conversation failures as typed events.  Preserve the complete JSON-capable
    event model under ``data`` so callers can inspect and reuse the original
    event information.  Convenience fields make common telemetry queries easy.
    Redaction is applied according to the active run configuration.
    """
    event_type = event.__class__.__name__
    record: dict[str, Any] = {
        "type": "openhands_event",
        "event_type": event_type,
        "source": str(getattr(event, "source", "")),
        "timestamp": str(getattr(event, "timestamp", "")),
    }

    event_id = getattr(event, "id", None)
    if event_id:
        record["event_id"] = str(event_id)

    if hasattr(event, "model_dump"):
        try:
            record["data"] = event.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - event capture must not stop a run
            try:
                record["data"] = event.model_dump()
            except Exception:  # noqa: BLE001 - retain metadata if serialization fails
                record["data_error"] = "event model could not be serialized"

    for field in ("action_id", "tool_call_id", "tool_name"):
        value = getattr(event, field, None)
        if value:
            record[field] = str(value)

    observation = getattr(event, "observation", None)
    if observation is not None and hasattr(observation, "is_error"):
        is_error = bool(observation.is_error)
        record["observation_is_error"] = is_error
        if is_error:
            record["error_kind"] = "tool_observation_error"

    error = getattr(event, "error", None)
    detail = getattr(event, "detail", None)
    if error or detail:
        # Keep a convenient error field in addition to the full structured data.
        record["error"] = redact(str(error or detail))

    classification = getattr(event, "classification", None)
    if classification is not None:
        kind = getattr(classification, "kind", None)
        retryable = getattr(classification, "retryable", None)
        if kind is not None:
            record["error_kind"] = str(getattr(kind, "value", kind))
        if retryable is not None:
            record["error_retryable"] = bool(retryable)

    for field in ("rejection_source", "rejection_reason", "code"):
        value = getattr(event, field, None)
        if value:
            record[field] = redact(str(value))

    return redact(record)


def gateway_url() -> str:
    """Read the Gateway URL from the environment."""
    return (os.getenv("ASTRA_GATEWAY_BASE_URL") or os.getenv("LLM_BASE_URL") or DEFAULT_GATEWAY_URL).rstrip("/")


def api_key() -> str:
    """Read and validate the Gateway API key from the environment."""
    value = os.getenv("ASTRA_GATEWAY_API_KEY") or os.getenv("LLM_API_KEY")
    if not value:
        raise ValueError("ASTRA_GATEWAY_API_KEY or LLM_API_KEY is required")
    if len(value) < 12 or any(char.isspace() for char in value):
        raise ValueError("Gateway API key does not look valid")
    return value


@contextmanager
def capture_gateway_responses(path: Path):
    """Enable per-run Gateway response capture without changing OpenHands behavior."""
    token = _gateway_response_path.set(path)
    try:
        yield
    finally:
        _gateway_response_path.reset(token)


def _response_payload(response: Any) -> Any:
    """Convert a LiteLLM response to a JSON-compatible provider payload."""
    if hasattr(response, "model_dump"):
        try:
            return response.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - fall back to the SDK's Python dump
            try:
                return response.model_dump()
            except Exception:  # noqa: BLE001 - capture must not stop a run
                pass
    if hasattr(response, "dict"):
        try:
            return response.dict()
        except Exception:  # noqa: BLE001 - capture must not stop a run
            pass
    if isinstance(response, dict):
        return response
    return str(response)


def _request_fingerprint(value: Any) -> Any:
    """Create a JSON-safe request view without retaining secrets or full payloads."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in ("authorization", "api_key", "apikey", "cookie", "password", "secret")):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = _request_fingerprint(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_request_fingerprint(item) for item in value]
    if isinstance(value, bytes):
        return {"type": "bytes", "size_bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _request_metadata(
    llm: Any,
    *,
    messages: Any = None,
    request_args: tuple[Any, ...] = (),
    request_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return safe logical request diagnostics available at the LiteLLM boundary."""
    base_url = str(getattr(llm, "base_url", ""))
    parsed = urlparse(base_url)
    logical_payload: dict[str, Any] = {
        "messages": messages,
        "args": request_args,
        "kwargs": request_kwargs or {},
    }
    fingerprint_payload = json.dumps(
        _request_fingerprint(logical_payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    headers: dict[str, str] = {}
    sources: list[dict[str, Any]] = [request_kwargs or {}]
    nested_headers = (request_kwargs or {}).get("headers")
    if isinstance(nested_headers, dict):
        sources.append(nested_headers)
    for source in sources:
        for key, value in source.items():
            key_text = str(key).lower().replace("_", "-")
            if key_text in {"content-length", "transfer-encoding", "content-type"}:
                headers[key_text] = str(value)
    return {
        "method": "POST",
        "url_path": parsed.path or "/",
        "body_size_bytes": len(fingerprint_payload),
        "body_sha256": hashlib.sha256(fingerprint_payload).hexdigest(),
        "body_scope": "redacted_logical_payload_at_litellm_boundary",
        "wire_body_observed": False,
        "framing_headers": {
            "content-length": headers.get("content-length", "unavailable"),
            "transfer-encoding": headers.get("transfer-encoding", "unavailable"),
            "content-type": headers.get("content-type", "unavailable"),
        },
    }


def _normalize_tool_call_arguments(
    value: Any,
    *,
    message_index: int,
    tool_call_index: int,
) -> tuple[str, bool]:
    """Return one valid JSON-object argument string for an assistant tool call.

    Strict OpenAI-compatible gateways validate historical tool calls, while
    some serializer paths represent absent arguments as an empty string.  An
    empty string is not JSON, so normalize only absent arguments to ``{}`` and
    fail locally for every other malformed value with a location-safe error.
    """
    normalized_empty = value is None or (isinstance(value, str) and not value.strip())
    if normalized_empty:
        return "{}", True
    if isinstance(value, Mapping):
        parsed: Any = dict(value)
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "invalid JSON in "
                f"messages[{message_index}].tool_calls[{tool_call_index}].function.arguments: "
                f"{exc.msg}"
            ) from exc
    else:
        raise ValueError(
            "unsupported tool-call argument type in "
            f"messages[{message_index}].tool_calls[{tool_call_index}]: {type(value).__name__}"
        )
    if not isinstance(parsed, dict):
        raise ValueError(
            "tool-call arguments must encode a JSON object in "
            f"messages[{message_index}].tool_calls[{tool_call_index}]"
        )
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":")), False


def _normalize_and_validate_messages(messages: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalize assistant tool-call history before delegating to LiteLLM.

    The returned messages are safe to serialize as JSON.  This is deliberately
    narrow: it repairs only absent tool arguments and rejects malformed
    historical tool calls rather than silently changing valid agent behavior.
    """
    if not isinstance(messages, list):
        raise ValueError("LLM messages must be a list")

    normalized_messages: list[dict[str, Any]] = []
    tool_call_count = 0
    normalized_empty_argument_count = 0
    declared_tool_call_ids: list[str] = []
    answered_tool_call_ids: set[str] = set()
    role_sequence: list[str] = []
    for message_index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            raise ValueError(f"messages[{message_index}] must be an object")
        normalized_message = dict(message)
        role_sequence.append(str(normalized_message.get("role")))
        if normalized_message.get("role") == "tool":
            call_id = normalized_message.get("tool_call_id")
            if isinstance(call_id, str):
                answered_tool_call_ids.add(call_id)
        tool_calls = normalized_message.get("tool_calls")
        if tool_calls is not None:
            if not isinstance(tool_calls, list):
                raise ValueError(f"messages[{message_index}].tool_calls must be a list")
            normalized_calls: list[dict[str, Any]] = []
            for tool_call_index, tool_call in enumerate(tool_calls):
                if not isinstance(tool_call, Mapping):
                    raise ValueError(
                        f"messages[{message_index}].tool_calls[{tool_call_index}] must be an object"
                    )
                normalized_call = dict(tool_call)
                function = normalized_call.get("function")
                if not isinstance(function, Mapping):
                    raise ValueError(
                        f"messages[{message_index}].tool_calls[{tool_call_index}].function must be an object"
                    )
                normalized_function = dict(function)
                arguments, normalized_empty = _normalize_tool_call_arguments(
                    normalized_function.get("arguments"),
                    message_index=message_index,
                    tool_call_index=tool_call_index,
                )
                normalized_function["arguments"] = arguments
                normalized_call["function"] = normalized_function
                normalized_calls.append(normalized_call)
                tool_call_count += 1
                normalized_empty_argument_count += int(normalized_empty)
                call_id = normalized_call.get("id")
                if isinstance(call_id, str):
                    declared_tool_call_ids.append(call_id)
            normalized_message["tool_calls"] = normalized_calls
        normalized_messages.append(normalized_message)

    try:
        json.dumps(normalized_messages, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"LLM message history is not JSON-serializable: {exc}") from exc

    orphaned_tool_call_ids = [call_id for call_id in declared_tool_call_ids if call_id not in answered_tool_call_ids]
    # Tool calls declared by the very last message are expected to be unanswered: that
    # message is what the model is about to be asked to continue from. Only interior gaps
    # (an assistant tool call that a later message never answers before another assistant
    # turn starts) indicate a genuinely malformed history.
    trailing_call_ids: set[str] = set()
    if normalized_messages and normalized_messages[-1].get("role") == "assistant":
        trailing_call_ids = {
            tool_call.get("id")
            for tool_call in (normalized_messages[-1].get("tool_calls") or [])
            if isinstance(tool_call, Mapping) and isinstance(tool_call.get("id"), str)
        }
    interior_orphaned_tool_call_ids = [call_id for call_id in orphaned_tool_call_ids if call_id not in trailing_call_ids]

    return normalized_messages, {
        "message_count": len(normalized_messages),
        "tool_call_count": tool_call_count,
        "normalized_empty_argument_count": normalized_empty_argument_count,
        "orphaned_tool_call_count": len(interior_orphaned_tool_call_ids),
        "orphaned_tool_call_ids": interior_orphaned_tool_call_ids[:20],
    }


def _response_header(source: Any, name: str) -> str | None:
    """Read one non-sensitive response header from an SDK response or exception."""
    headers = getattr(source, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get(name) if hasattr(headers, "get") else None
    except Exception:  # noqa: BLE001 - diagnostics must never affect a run
        return None
    return str(value) if value is not None else None


def _response_status(source: Any) -> int | None:
    """Extract an HTTP status code when LiteLLM exposes one."""
    for candidate in (source, getattr(source, "response", None)):
        for field in ("status_code", "status"):
            value = getattr(candidate, field, None)
            if isinstance(value, int) and 100 <= value <= 599:
                return value
    return None


def _error_body(error: Exception) -> str | None:
    """Return a bounded, redacted provider error body when the SDK exposes one."""
    response = getattr(error, "response", None)
    candidates = [
        getattr(response, "text", None),
        getattr(response, "content", None),
        getattr(error, "body", None),
        getattr(error, "detail", None),
    ]
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if isinstance(value, (dict, list)):
            value = json.dumps(redact(value), separators=(",", ":"))
        text = str(value).strip()
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                text = json.dumps(redact(parsed), separators=(",", ":"))
            else:
                for key in ("authorization", "api_key", "apikey", "cookie", "password", "secret", "token"):
                    text = re.sub(rf'("{key}"\s*:\s*")[^"]*(")', r'\1[REDACTED]\2', text, flags=re.IGNORECASE)
                    text = re.sub(rf'({key}\s*[=:]\s*)[^,;\s}}]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
            return redact(text)[:_GATEWAY_ERROR_BODY_MAX_CHARS]
    return None


# Reproduced by replaying the exact same request immediately after this failure: it
# succeeds. This is a one-off gateway/provider hiccup, not a genuinely malformed
# request, so unlike other 400s (which are not retried, since retrying a truly bad
# request only wastes time) this specific signature gets a few quick attempts before
# it is allowed to end the run.
_INVALID_BODY_MAX_ATTEMPTS = 3
_INVALID_BODY_RETRY_DELAY_SECONDS = 2.0


def _is_transient_invalid_body_error(error: Exception) -> bool:
    """Return whether this is the gateway's transient "invalid_body" rejection."""
    if _response_status(error) != 400:
        return False
    body = (_error_body(error) or "").lower()
    return "invalid_body" in body or "request body must be valid json" in body


class StuckRequestError(RuntimeError):
    """Raised instead of making a call that has already failed identically too many
    times, so a request that will not succeed stops burning the rest of the run's
    time budget instead of being retried again.
    """


# Retrying an unrecoverable request (this is not the internal loop above -- it is
# every top-level call the *agent* makes for what is, byte-for-byte, the same
# conversation state) was observed taking ~15 minutes per attempt and repeating with
# no progress. Nothing in this module controls whether the agent retries a failed
# turn; the only lever available is refusing to attempt an identical request again
# once it has already failed this many times in a row.
_STUCK_REQUEST_MAX_CONSECUTIVE_FAILURES = 2


def _messages_fingerprint(messages: list[dict[str, Any]]) -> str:
    """Return a stable identity for a message history, to recognize an exact repeat."""
    encoded = json.dumps(messages, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _repeat_failure_tracker(llm: Any) -> dict[str, int]:
    """Return the per-LLM-instance map of {request fingerprint: consecutive failures}."""
    tracker = getattr(llm, "_astra_repeat_failure_tracker", None)
    if not isinstance(tracker, dict):
        tracker = {}
        setattr(llm, "_astra_repeat_failure_tracker", tracker)
    return tracker


def _record_repeat_outcome(llm: Any, fingerprint: str, *, failed: bool) -> int:
    """Update the failure tracker for one fingerprint and return its new count.

    A success clears that fingerprint's count (it is no longer stuck), which also
    means a later retry of the same content after real progress starts counting
    from zero, exactly as intended.
    """
    tracker = _repeat_failure_tracker(llm)
    if failed:
        tracker[fingerprint] = tracker.get(fingerprint, 0) + 1
    else:
        tracker.pop(fingerprint, None)
    if len(tracker) > 64:  # bound memory on a very long-running conversation
        for stale_key in list(tracker)[:-64]:
            del tracker[stale_key]
    return tracker.get(fingerprint, 0)


def _dump_failed_request(
    response_path: Path,
    *,
    messages: Any,
    request_kwargs: dict[str, Any] | None,
    record: dict[str, Any],
) -> Path | None:
    """Persist the exact, uncapped message array for a failed call.

    ``gateway_response_path`` only ever stores a bounded, redacted summary so
    a run's telemetry stays small. When a call errors, that summary is not
    enough to diagnose gateway-side rejections (malformed history, dangling
    tool calls, provider-specific fields). Write the full request alongside
    it, one file per failure, so the next occurrence is debuggable without a
    fresh repro.
    """
    if messages is None:
        return None
    try:
        dump_dir = response_path.parent / f"{response_path.stem}_failures"
        dump_dir.mkdir(parents=True, exist_ok=True)
        timestamp = now().replace(":", "").replace("+", "")
        dump_path = dump_dir / f"{timestamp}-{record.get('model', 'unknown')}.json".replace("/", "_")
        payload = {
            "timestamp": record.get("timestamp"),
            "model": record.get("model"),
            "error": record.get("error"),
            "status_code": record.get("status_code"),
            "request_validation": record.get("request_validation"),
            "messages": messages,
            "request_kwargs": {key: value for key, value in (request_kwargs or {}).items() if key != "headers"},
        }
        dump_path.write_text(json.dumps(redact(payload), indent=2, ensure_ascii=False), encoding="utf-8")
        return dump_path
    except Exception as exc:  # noqa: BLE001 - diagnostics must never affect a run
        warnings.warn(f"Could not dump failed gateway request: {exc}", RuntimeWarning, stacklevel=2)
        return None


def _capture_gateway_response(
    llm: Any,
    response: Any = None,
    error: Exception | None = None,
    latency_ms: float | None = None,
    messages: Any = None,
    request_args: tuple[Any, ...] = (),
    request_kwargs: dict[str, Any] | None = None,
    request_validation: dict[str, Any] | None = None,
) -> None:
    """Persist a bounded response record without affecting the run."""
    path = _gateway_response_path.get()
    if path is None:
        return
    try:
        record: dict[str, Any] = {
            "type": "gateway_response",
            "timestamp": now(),
            "model": str(getattr(llm, "model", "")),
            "status": "error" if error else "ok",
        }
        if latency_ms is not None:
            record["latency_ms"] = round(max(0.0, latency_ms), 3)
        record["request"] = _request_metadata(
            llm,
            messages=messages,
            request_args=request_args,
            request_kwargs=request_kwargs,
        )
        if request_validation is not None:
            record["request_validation"] = request_validation
        response_source = getattr(error, "response", None) if error is not None else response
        status_code = _response_status(response_source)
        if status_code is not None:
            record["status_code"] = status_code
        request_id = next(
            (
                _response_header(response_source, header)
                for header in ("x-request-id", "request-id", "x-correlation-id", "trace-id")
                if _response_header(response_source, header)
            ),
            None,
        )
        if request_id is not None:
            record["request_id"] = request_id
        if error is not None:
            record["error"] = {"type": error.__class__.__name__, "message": str(error)}
            body = _error_body(error)
            if body is not None:
                record["error_body"] = body
            dump_path = _dump_failed_request(path, messages=messages, request_kwargs=request_kwargs, record=record)
            if dump_path is not None:
                record["request_dump_path"] = str(dump_path)
        else:
            record["response"] = _response_payload(response)
            hidden_params = getattr(response, "_hidden_params", None)
            if isinstance(hidden_params, dict):
                record["hidden_params"] = hidden_params

        rendered = json.dumps(redact(record), separators=(",", ":"))
        encoded_size = len(rendered.encode("utf-8"))
        if encoded_size > _GATEWAY_RESPONSE_MAX_BYTES:
            record.pop("response", None)
            record["response_truncated"] = True
            record["response_size_bytes"] = encoded_size
            rendered = json.dumps(redact(record), separators=(",", ":"))

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
    except Exception as exc:  # noqa: BLE001 - observability must be fail-open
        warnings.warn(
            f"Could not capture HackerRank Gateway response: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )


def _is_gemini_model(llm: Any) -> bool:
    """Return whether an LLM instance targets a Gemini model."""
    return "gemini" in str(getattr(llm, "model", "")).lower()


def _field_value(value: Any, field: str) -> Any:
    """Read a field from either a mapping or a LiteLLM model object."""
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def _thought_signature(tool_call: Any) -> str | None:
    """Extract Gemini's provider-specific thought signature from a tool call."""
    extra_content = _field_value(tool_call, "extra_content")
    if not isinstance(extra_content, dict):
        return None
    google = extra_content.get("google")
    if not isinstance(google, dict):
        return None
    signature = google.get("thought_signature")
    return signature if isinstance(signature, str) and signature else None


def _remember_gemini_signatures(llm: Any, response: Any) -> None:
    """Cache provider metadata needed to replay Gemini tool-call turns."""
    if not _is_gemini_model(llm):
        return
    signatures = getattr(llm, "_astra_gemini_thought_signatures", None)
    if not isinstance(signatures, dict):
        signatures = {}
        setattr(llm, "_astra_gemini_thought_signatures", signatures)

    for choice in getattr(response, "choices", None) or []:
        message = _field_value(choice, "message")
        for tool_call in _field_value(message, "tool_calls") or []:
            call_id = _field_value(tool_call, "id")
            signature = _thought_signature(tool_call)
            if call_id and signature:
                signatures[str(call_id)] = signature

    # Bound this per-LLM cache because tool-call IDs are unique across a run.
    if len(signatures) > 256:
        for call_id in list(signatures)[:-256]:
            del signatures[call_id]


def _restore_gemini_signatures(llm: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Restore Gemini signatures that OpenHands omits when serializing history."""
    if not _is_gemini_model(llm):
        return messages
    signatures = getattr(llm, "_astra_gemini_thought_signatures", None)
    if not isinstance(signatures, dict) or not signatures:
        return messages

    restored_messages: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("tool_calls"), list):
            restored_messages.append(message)
            continue

        restored_calls: list[Any] = []
        message_changed = False
        for tool_call in message["tool_calls"]:
            if not isinstance(tool_call, dict):
                restored_calls.append(tool_call)
                continue
            call_id = tool_call.get("id")
            signature = signatures.get(str(call_id)) if call_id else None
            if signature and not _thought_signature(tool_call):
                extra_content = tool_call.get("extra_content")
                extra_content = dict(extra_content) if isinstance(extra_content, dict) else {}
                google = extra_content.get("google")
                google = dict(google) if isinstance(google, dict) else {}
                google["thought_signature"] = signature
                extra_content["google"] = google
                restored_call = dict(tool_call)
                restored_call["extra_content"] = extra_content
                restored_calls.append(restored_call)
                message_changed = True
            else:
                restored_calls.append(tool_call)

        if message_changed:
            restored_message = dict(message)
            restored_message["tool_calls"] = restored_calls
            restored_messages.append(restored_message)
        else:
            restored_messages.append(message)
    return restored_messages


def install_gateway_fix(base_url: str) -> None:
    """Adapt OpenHands requests for the HackerRank Gateway, including Gemini."""
    parsed = urlparse(base_url)
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Gateway base URL must contain a host and must not contain credentials")
    from openhands.sdk import LLM

    original_sync = LLM._transport_call
    original_async = LLM._atransport_call
    original_responses = LLM.responses
    original_aresponses = LLM.aresponses
    if getattr(original_sync, "_astra_gateway_fix", False):
        return

    def sync_call(self: Any, *, messages: list[dict[str, Any]], **kwargs: Any):
        if _is_gemini_model(self):
            messages = _restore_gemini_signatures(self, messages)
            kwargs.pop("prompt_cache_key", None)
            extra = kwargs.get("extra_body")
            if isinstance(extra, dict):
                kwargs["extra_body"] = {key: value for key, value in extra.items() if key != "prompt_cache_key"}
        messages = [{key: value for key, value in message.items() if key not in {"name", "refusal"}} for message in messages]
        messages, request_validation = _normalize_and_validate_messages(messages)
        fingerprint = _messages_fingerprint(messages)
        prior_failures = _repeat_failure_tracker(self).get(fingerprint, 0)
        if prior_failures >= _STUCK_REQUEST_MAX_CONSECUTIVE_FAILURES:
            error = StuckRequestError(
                f"an identical request has already failed {prior_failures} times in a row "
                f"(fingerprint={fingerprint[:12]}); treating it as stuck rather than retrying again"
            )
            _capture_gateway_response(self, error=error, latency_ms=0.0, messages=messages, request_kwargs=kwargs, request_validation=request_validation)
            raise error
        for attempt in range(1, _INVALID_BODY_MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                response = original_sync(self, messages=messages, **kwargs)
            except Exception as exc:
                _capture_gateway_response(self, error=exc, latency_ms=(time.perf_counter() - started) * 1000, messages=messages, request_kwargs=kwargs, request_validation=request_validation)
                if attempt < _INVALID_BODY_MAX_ATTEMPTS and _is_transient_invalid_body_error(exc):
                    time.sleep(_INVALID_BODY_RETRY_DELAY_SECONDS)
                    continue
                _record_repeat_outcome(self, fingerprint, failed=True)
                raise
            _remember_gemini_signatures(self, response)
            _record_repeat_outcome(self, fingerprint, failed=False)
            _capture_gateway_response(self, response=response, latency_ms=(time.perf_counter() - started) * 1000, messages=messages, request_kwargs=kwargs, request_validation=request_validation)
            return response

    async def async_call(self: Any, *, messages: list[dict[str, Any]], **kwargs: Any):
        if _is_gemini_model(self):
            messages = _restore_gemini_signatures(self, messages)
            kwargs.pop("prompt_cache_key", None)
            extra = kwargs.get("extra_body")
            if isinstance(extra, dict):
                kwargs["extra_body"] = {key: value for key, value in extra.items() if key != "prompt_cache_key"}
        messages = [{key: value for key, value in message.items() if key not in {"name", "refusal"}} for message in messages]
        messages, request_validation = _normalize_and_validate_messages(messages)
        fingerprint = _messages_fingerprint(messages)
        prior_failures = _repeat_failure_tracker(self).get(fingerprint, 0)
        if prior_failures >= _STUCK_REQUEST_MAX_CONSECUTIVE_FAILURES:
            error = StuckRequestError(
                f"an identical request has already failed {prior_failures} times in a row "
                f"(fingerprint={fingerprint[:12]}); treating it as stuck rather than retrying again"
            )
            _capture_gateway_response(self, error=error, latency_ms=0.0, messages=messages, request_kwargs=kwargs, request_validation=request_validation)
            raise error
        for attempt in range(1, _INVALID_BODY_MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                response = await original_async(self, messages=messages, **kwargs)
            except Exception as exc:
                _capture_gateway_response(self, error=exc, latency_ms=(time.perf_counter() - started) * 1000, messages=messages, request_kwargs=kwargs, request_validation=request_validation)
                if attempt < _INVALID_BODY_MAX_ATTEMPTS and _is_transient_invalid_body_error(exc):
                    await asyncio.sleep(_INVALID_BODY_RETRY_DELAY_SECONDS)
                    continue
                _record_repeat_outcome(self, fingerprint, failed=True)
                raise
            _remember_gemini_signatures(self, response)
            _record_repeat_outcome(self, fingerprint, failed=False)
            _capture_gateway_response(self, response=response, latency_ms=(time.perf_counter() - started) * 1000, messages=messages, request_kwargs=kwargs, request_validation=request_validation)
            return response

    def responses_call(self: Any, *args: Any, **kwargs: Any):
        started = time.perf_counter()
        try:
            result = original_responses(self, *args, **kwargs)
        except Exception as exc:
            _capture_gateway_response(self, error=exc, latency_ms=(time.perf_counter() - started) * 1000, request_args=args, request_kwargs=kwargs)
            raise
        _capture_gateway_response(
            self,
            response=getattr(result, "raw_response", result),
            latency_ms=(time.perf_counter() - started) * 1000,
            request_args=args,
            request_kwargs=kwargs,
        )
        return result

    async def aresponses_call(self: Any, *args: Any, **kwargs: Any):
        started = time.perf_counter()
        try:
            result = await original_aresponses(self, *args, **kwargs)
        except Exception as exc:
            _capture_gateway_response(self, error=exc, latency_ms=(time.perf_counter() - started) * 1000, request_args=args, request_kwargs=kwargs)
            raise
        _capture_gateway_response(
            self,
            response=getattr(result, "raw_response", result),
            latency_ms=(time.perf_counter() - started) * 1000,
            request_args=args,
            request_kwargs=kwargs,
        )
        return result

    sync_call._astra_gateway_fix = True
    async_call._astra_gateway_fix = True
    responses_call._astra_gateway_fix = True
    aresponses_call._astra_gateway_fix = True
    LLM._transport_call = sync_call
    LLM._atransport_call = async_call
    LLM.responses = responses_call
    LLM.aresponses = aresponses_call


@dataclass(frozen=True)
class RunResult:
    """Minimal result returned by the wrapper."""

    status: str
    exit_code: int
    started_at: str
    completed_at: str
    events_path: Path
    error: dict[str, str] | None = None


def run(
    workspace: Path,
    instruction_file: Path,
    model: str,
    reasoning: str,
    output_dir: Path,
    gateway_base_url: str | None = None,
    env_file: Path | None = None,
    redact_output: bool = False,
) -> RunResult:
    """Run one OpenHands coding session and write JSONL event records."""
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "events.jsonl"
    gateway_responses_path = output_dir / "gateway_responses.jsonl"
    # Each output directory represents one run.  Truncate stale captures so
    # telemetry never aggregates Gateway responses from an earlier run.
    gateway_responses_path.write_text("", encoding="utf-8")
    started_at = now()
    status, exit_code, error = "completed", 0, None
    workspace_before = None
    workspace_snapshot_error: str | None = None
    redaction_token = _redaction_enabled.set(redact_output)

    def workspace_event() -> dict[str, Any]:
        """Capture final workspace changes without masking the run result."""
        if workspace_before is None:
            return {
                "type": "workspace_metrics",
                "status": "unavailable",
                "reason": workspace_snapshot_error or "workspace snapshot was not captured",
            }
        try:
            workspace_after = snapshot_workspace(workspace, excluded_paths=(output_dir,))
            return {"type": "workspace_metrics", **compare_snapshots(workspace_before, workspace_after)}
        except Exception as exc:  # noqa: BLE001 - metrics must not hide run errors
            return {"type": "workspace_metrics", "status": "unavailable", "reason": f"{exc.__class__.__name__}: {exc}"}

    try:
        # Explicit shell variables win. When no file is supplied, load .env from
        # the directory where the user invoked the command.
        load_dotenv(dotenv_path=env_file or Path.cwd() / ".env", override=False)
        if not workspace.is_dir():
            raise ValueError(f"workspace does not exist: {workspace}")
        if not instruction_file.is_file():
            raise ValueError(f"instruction file does not exist: {instruction_file}")
        if reasoning not in REASONING_OPTIONS:
            raise ValueError(f"unsupported reasoning effort: {reasoning}")
        instruction = instruction_file.read_text(encoding="utf-8")
        key = api_key()
        base_url = (gateway_base_url or gateway_url()).rstrip("/")
        install_gateway_fix(base_url)
        try:
            workspace_before = snapshot_workspace(workspace, excluded_paths=(output_dir,))
        except Exception as exc:  # noqa: BLE001 - metrics must not prevent the run
            workspace_snapshot_error = f"{exc.__class__.__name__}: {exc}"

        from openhands.sdk import Agent, Conversation, Event, LLM
        from openhands.sdk.context.condenser import LLMSummarizingCondenser
        from openhands.sdk.tool import Tool
        from openhands.tools.file_editor import FileEditorTool
        from openhands.tools.terminal import TerminalTool

        normalized_model = normalize_gateway_model(model)
        llm = LLM(
            usage_id="agent",
            model=normalized_model,
            api_key=SecretStr(key),
            base_url=base_url,
            force_string_serializer=True,
            # Pass the requested value through unchanged. OpenHands and the
            # Gateway/model capability layer determine whether the selected
            # effort is supported for this model.
            reasoning_effort=reasoning,
            # OpenHands defaults custom gateway routes to a 16,384-token
            # output cap.  Allow longer coding-agent turns; the gateway and
            # model context window remain the final authorities.
            max_output_tokens=32768,
            # LiteLLM has no built-in context window for most of these custom aliases.
            # ``max_input_tokens`` always wins over any runtime/static resolution and
            # is what the condenser below uses to decide when to summarize history;
            # every model gets a value now, confirmed or conservative-default (see
            # gateway_model_max_input_tokens).
            max_input_tokens=gateway_model_max_input_tokens(model),
            # SDK default is 300s per attempt; large-context turns on slower models
            # have been observed taking longer than that to respond, so requests were
            # timing out (and being retried) on responses that would have succeeded
            # given more patience. 1200s (20 min) per attempt gives real slow turns
            # room to complete instead of being cut off partway through.
            timeout=1200,
            # SDK default is 5 internal retries per call. Combined with the longer
            # timeout above, 5 retries could mean up to ~100 minutes before a single
            # call gives up (5 x 1200s) -- and that is *before* any retry the agent
            # itself performs on top. 2 keeps a real safety net for a one-off blip
            # without multiplying the longer per-attempt patience into an
            # unbounded-feeling wait when a request is genuinely stuck, not slow.
            num_retries=2,
        )

        with events_path.open("w", encoding="utf-8") as stream:
            def write(record: dict[str, Any]) -> None:
                stream.write(json.dumps(redact(record), separators=(",", ":")) + "\n")
                stream.flush()

            write({"type": "run_event", "event_type": "run_started", "timestamp": started_at, "model": normalized_model, "reasoning": reasoning})

            def callback(event: Event) -> None:
                # Preserve every event emitted by OpenHands.  Telemetry later
                # selects action/outcome events, while the event stream remains
                # available for other downstream consumers.
                record = _event_record(event)
                tool_call = getattr(event, "tool_call", None)
                if tool_call is not None and getattr(tool_call, "name", None):
                    record["tool_name"] = str(tool_call.name)
                write(record)

            # Without a condenser, conversation history grows unbounded for every model
            # until the provider hard-rejects an oversized request (or, observed
            # separately, just becomes slow/unreliable to respond well before that
            # point) and the whole run is lost. Summarizing with the same LLM keeps
            # this self-contained. The token-based trigger defers to
            # llm.effective_max_input_tokens (max_input_tokens, always set now -- see
            # gateway_model_max_input_tokens). max_size is the SDK's default of 240
            # events lowered to 80: the default is a per-model-context-window-sized
            # ceiling that a normal task rarely approaches, so it is not a real bound
            # in practice; 80 forces every model's history to actually stay small on a
            # predictable cadence, independent of any one model's token limit.
            condenser = LLMSummarizingCondenser(llm=llm, max_size=80)
            agent = Agent(llm=llm, tools=[Tool(name=TerminalTool.name), Tool(name=FileEditorTool.name)], condenser=condenser)
            conversation = Conversation(agent=agent, callbacks=[callback], workspace=str(workspace))
            with capture_gateway_responses(gateway_responses_path):
                conversation.send_message(instruction)
                conversation.run()

            metrics = getattr(llm, "metrics", None)
            usage = getattr(metrics, "accumulated_token_usage", None) if metrics else None
            write({
                "type": "openhands_metrics",
                "model": normalized_model,
                "reasoning": reasoning,
                "input_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "output_tokens": getattr(usage, "completion_tokens", None) if usage else None,
                "cache_read_input_tokens": getattr(usage, "cache_read_tokens", None) if usage else None,
                "cache_creation_input_tokens": getattr(usage, "cache_write_tokens", None) if usage else None,
                "reasoning_tokens": getattr(usage, "reasoning_tokens", None) if usage else None,
                "cost_usd": getattr(metrics, "accumulated_cost", None) if metrics else None,
            })
            write(workspace_event())
            write({"type": "run_event", "event_type": "run_completed", "timestamp": now()})
    except Exception as exc:  # noqa: BLE001 - expose a useful failure to the caller
        status, exit_code = "failed", 1
        error = {"type": exc.__class__.__name__, "message": str(exc)}
        with events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(redact(workspace_event()), separators=(",", ":")) + "\n")
            stream.write(json.dumps(redact({"type": "run_event", "event_type": "run_failed", "timestamp": now(), "error": error}), separators=(",", ":")) + "\n")
    finally:
        _redaction_enabled.reset(redaction_token)

    return RunResult(status, exit_code, started_at, now(), events_path, error)
