"""Run one OpenHands SDK conversation and emit benchmark-safe JSON events."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from openhands.sdk import Agent, Conversation, Event, LLM, LLMConvertibleEvent
from openhands.sdk.tool import Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool


def _portable_gateway_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove optional OpenAI fields rejected by the internal portable route.

    The HackerRank gateway accepts the OpenAI chat-completions shape but rejects
    ``name`` and ``refusal`` fields when they are present in conversation
    history.  These fields are optional metadata; tool calls, tool IDs, roles,
    and content remain unchanged.
    """
    return [
        {
            key: value
            for key, value in message.items()
            if key not in {"name", "refusal"}
        }
        for message in messages
    ]


def _without_gemini_prompt_cache_key(model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Remove LiteLLM's prompt-cache field for Gemini gateway requests.

    The gateway accepts the OpenAI chat-completions contract, but the Gemini
    route rejects ``prompt_cache_key`` instead of ignoring it.  LiteLLM can
    place the field at the transport level or inside a nested request-options
    mapping, so scrub the exact key recursively only for Gemini models.
    """
    model_name = model.rsplit("/", 1)[-1].lower()
    if not model_name.startswith("gemini-"):
        return kwargs

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: scrub(item)
                for key, item in value.items()
                if key != "prompt_cache_key"
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(kwargs)


def _install_portable_gateway_compatibility() -> None:
    """Patch the SDK transport boundary for the configured portable gateway."""
    if "gateway-central.ai.private.hackerrank.link" not in (
        os.getenv("LLM_BASE_URL") or ""
    ):
        return

    original_transport_call = LLM._transport_call
    original_async_transport_call = LLM._atransport_call
    if getattr(original_transport_call, "_astra_gateway_compatible", False):
        return

    def transport_call(self: LLM, *, messages: list[dict[str, Any]], **kwargs: Any):
        kwargs = _without_gemini_prompt_cache_key(str(self.model), kwargs)
        return original_transport_call(
            self,
            messages=_portable_gateway_messages(messages),
            **kwargs,
        )

    transport_call._astra_gateway_compatible = True
    LLM._transport_call = transport_call

    async def async_transport_call(
        self: LLM, *, messages: list[dict[str, Any]], **kwargs: Any
    ):
        kwargs = _without_gemini_prompt_cache_key(str(self.model), kwargs)
        return await original_async_transport_call(
            self,
            messages=_portable_gateway_messages(messages),
            **kwargs,
        )

    async_transport_call._astra_gateway_compatible = True
    LLM._atransport_call = async_transport_call


def _json_value(value: Any) -> Any:
    """Convert SDK/Pydantic values into JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _event_record(event: Event) -> dict[str, Any]:
    """Emit only event metadata needed for trajectory/tool telemetry."""
    record: dict[str, Any] = {
        "type": "openhands_event",
        "event_type": event.__class__.__name__,
        "source": getattr(event, "source", None),
        "timestamp": getattr(event, "timestamp", None),
    }
    tool_name = getattr(event, "tool_name", None)
    if tool_name:
        record["tool_name"] = str(tool_name)
    tool_call = getattr(event, "tool_call", None)
    if tool_call is not None and getattr(tool_call, "name", None):
        record["tool_name"] = str(tool_call.name)
    action = getattr(event, "action", None)
    if action is not None:
        action_type = getattr(action, "__class__", type(action)).__name__
        record["action_type"] = action_type
    return record


def _metric_value(metrics: Any, name: str) -> int | float | None:
    """Read a metrics field across SDK versions without leaking raw objects."""
    value = getattr(metrics, name, None)
    if value is None:
        usage = getattr(metrics, "accumulated_token_usage", None)
        value = getattr(usage, name, None) if usage is not None else None
    if isinstance(value, (int, float)):
        return value
    return None


def _emit_metrics(llm: LLM, model: str, reasoning: str) -> None:
    """Write one normalized usage record understood by astra_harness.telemetry."""
    metrics = llm.metrics
    usage = getattr(metrics, "accumulated_token_usage", None)
    payload = {
        "type": "astra_openhands_metrics",
        "model": model,
        "reasoning": reasoning,
        "input_tokens": _metric_value(usage or metrics, "prompt_tokens"),
        "output_tokens": _metric_value(usage or metrics, "completion_tokens"),
        "cache_read_input_tokens": _metric_value(usage or metrics, "cache_read_tokens"),
        "cache_creation_input_tokens": _metric_value(usage or metrics, "cache_write_tokens"),
        "reasoning_tokens": _metric_value(usage or metrics, "reasoning_tokens"),
        "cost_usd": getattr(metrics, "accumulated_cost", None),
    }
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an OpenHands SDK task")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--instruction", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", choices=("low", "medium", "high", "xhigh", "max"), default="medium")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.workspace.is_dir():
        print(f"workspace does not exist: {args.workspace}", file=sys.stderr)
        return 2
    try:
        instruction = args.instruction.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read instruction: {exc}", file=sys.stderr)
        return 2
    # The local HackerRank gateway env file uses ASTRA_GATEWAY_API_KEY. Keep
    # the generic OpenHands names supported while accepting that convention
    # without copying or logging the secret.
    api_key = os.getenv("LLM_API_KEY") or os.getenv("ASTRA_GATEWAY_API_KEY")
    if not api_key:
        print("LLM_API_KEY is required", file=sys.stderr)
        return 2
    # OpenHands currently documents high/xhigh but not max. Keep the common
    # harness surface while mapping max to the strongest supported SDK value.
    sdk_reasoning = "high" if args.reasoning == "max" else args.reasoning
    gateway_base_url = os.getenv("LLM_BASE_URL") or os.getenv("ASTRA_GATEWAY_BASE_URL")
    if not gateway_base_url and os.getenv("ASTRA_GATEWAY_API_KEY"):
        gateway_base_url = "https://gateway-central.ai.private.hackerrank.link/v1"
    llm = LLM(
        usage_id="agent",
        model=args.model,
        api_key=SecretStr(api_key),
        base_url=gateway_base_url or None,
        force_string_serializer=True,
        reasoning_effort=sdk_reasoning,
    )
    if gateway_base_url and not os.getenv("LLM_BASE_URL"):
        os.environ["LLM_BASE_URL"] = gateway_base_url
    _install_portable_gateway_compatibility()

    def callback(event: Event) -> None:
        if isinstance(event, LLMConvertibleEvent) or getattr(event, "tool_name", None):
            print(json.dumps(_event_record(event), separators=(",", ":")), flush=True)

    agent = Agent(
        llm=llm,
        tools=[Tool(name=TerminalTool.name), Tool(name=FileEditorTool.name)],
    )
    conversation = Conversation(agent=agent, callbacks=[callback], workspace=str(args.workspace))
    try:
        conversation.send_message(instruction)
        conversation.run()
        _emit_metrics(llm, args.model, args.reasoning)
    except Exception as exc:  # noqa: BLE001 - preserve the provider failure in stderr
        print(f"OpenHands task failed: {exc}", file=sys.stderr)
        try:
            _emit_metrics(llm, args.model, args.reasoning)
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
