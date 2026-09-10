"""Small, task-agnostic OpenHands + HackerRank Gateway wrapper."""

from __future__ import annotations

import json
import os
import time
import warnings
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import SecretStr

from .workspace_metrics import compare_snapshots, snapshot_workspace


DEFAULT_GATEWAY_URL = "https://gateway-central.ai.private.hackerrank.link/v1"
REASONING_OPTIONS = ("none", "minimal", "low", "medium", "high", "xhigh", "ultra", "max")
_GATEWAY_RESPONSE_MAX_BYTES = 2 * 1024 * 1024
_gateway_response_path: ContextVar[Path | None] = ContextVar("gateway_response_path", default=None)
_redaction_enabled: ContextVar[bool] = ContextVar("redaction_enabled", default=True)


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


def _capture_gateway_response(
    llm: Any,
    response: Any = None,
    error: Exception | None = None,
    latency_ms: float | None = None,
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
        if error is not None:
            record["error"] = {"type": error.__class__.__name__, "message": str(error)}
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


def install_gateway_fix(base_url: str) -> None:
    """Adapt OpenHands requests for the HackerRank Gateway, including Gemini."""
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Gateway base URL must be HTTPS and must not contain credentials")
    if "gateway-central.ai.private.hackerrank.link" not in base_url:
        return

    from openhands.sdk import LLM

    original_sync = LLM._transport_call
    original_async = LLM._atransport_call
    original_responses = LLM.responses
    original_aresponses = LLM.aresponses
    if getattr(original_sync, "_astra_gateway_fix", False):
        return

    def sync_call(self: Any, *, messages: list[dict[str, Any]], **kwargs: Any):
        if "gemini" in str(getattr(self, "model", "")).lower():
            kwargs.pop("prompt_cache_key", None)
            extra = kwargs.get("extra_body")
            if isinstance(extra, dict):
                kwargs["extra_body"] = {key: value for key, value in extra.items() if key != "prompt_cache_key"}
        messages = [{key: value for key, value in message.items() if key not in {"name", "refusal"}} for message in messages]
        started = time.perf_counter()
        try:
            response = original_sync(self, messages=messages, **kwargs)
        except Exception as exc:
            _capture_gateway_response(self, error=exc, latency_ms=(time.perf_counter() - started) * 1000)
            raise
        _capture_gateway_response(self, response=response, latency_ms=(time.perf_counter() - started) * 1000)
        return response

    async def async_call(self: Any, *, messages: list[dict[str, Any]], **kwargs: Any):
        if "gemini" in str(getattr(self, "model", "")).lower():
            kwargs.pop("prompt_cache_key", None)
            extra = kwargs.get("extra_body")
            if isinstance(extra, dict):
                kwargs["extra_body"] = {key: value for key, value in extra.items() if key != "prompt_cache_key"}
        messages = [{key: value for key, value in message.items() if key not in {"name", "refusal"}} for message in messages]
        started = time.perf_counter()
        try:
            response = await original_async(self, messages=messages, **kwargs)
        except Exception as exc:
            _capture_gateway_response(self, error=exc, latency_ms=(time.perf_counter() - started) * 1000)
            raise
        _capture_gateway_response(self, response=response, latency_ms=(time.perf_counter() - started) * 1000)
        return response

    def responses_call(self: Any, *args: Any, **kwargs: Any):
        started = time.perf_counter()
        try:
            result = original_responses(self, *args, **kwargs)
        except Exception as exc:
            _capture_gateway_response(self, error=exc, latency_ms=(time.perf_counter() - started) * 1000)
            raise
        _capture_gateway_response(
            self,
            response=getattr(result, "raw_response", result),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return result

    async def aresponses_call(self: Any, *args: Any, **kwargs: Any):
        started = time.perf_counter()
        try:
            result = await original_aresponses(self, *args, **kwargs)
        except Exception as exc:
            _capture_gateway_response(self, error=exc, latency_ms=(time.perf_counter() - started) * 1000)
            raise
        _capture_gateway_response(
            self,
            response=getattr(result, "raw_response", result),
            latency_ms=(time.perf_counter() - started) * 1000,
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
        from openhands.sdk.tool import Tool
        from openhands.tools.file_editor import FileEditorTool
        from openhands.tools.terminal import TerminalTool

        normalized_model = model if "/" in model else f"openai/{model}"
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

            agent = Agent(llm=llm, tools=[Tool(name=TerminalTool.name), Tool(name=FileEditorTool.name)])
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
