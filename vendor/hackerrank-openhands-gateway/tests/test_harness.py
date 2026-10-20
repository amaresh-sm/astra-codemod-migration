import asyncio
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from types import SimpleNamespace

import pytest

from hackerrank_openhands import harness
from hackerrank_openhands.harness import (
    _enable_anthropic_messages_streaming,
    _event_record,
    _normalize_and_validate_messages,
    _remember_gemini_signatures,
    _restore_gemini_signatures,
    redact,
    gateway_transport_base_url,
    normalize_gateway_model,
    resolved_transport,
)
from hackerrank_openhands.telemetry import collect
from hackerrank_openhands.pricing import MASTER_MODEL_NAMES, PRICING_TABLE, estimate_custom_cost, normalize_model_name
from hackerrank_openhands.workspace_metrics import compare_snapshots, snapshot_workspace


def test_redacts_credentials():
    assert redact({"Authorization": "Bearer abcdefghijklmnop"}) == {"Authorization": "[REDACTED]"}
    assert redact({"Authorization": "Bearer abcdefghijklmnop"}, enabled=False) == {
        "Authorization": "Bearer abcdefghijklmnop"
    }


def test_claude_prompt_caching_replaces_openai_prefix_with_anthropic_prefix():
    assert normalize_gateway_model("openai/claude-opus-5-5", use_anthropic_format=True) == "anthropic/claude-opus-5-5"
    assert normalize_gateway_model("claude-opus-5-5", use_anthropic_format=True) == "anthropic/claude-opus-5-5"
    assert normalize_gateway_model("openai/claude-opus-5-5") == "openai/claude-opus-5-5"
    assert resolved_transport("anthropic/claude-opus-5-5") == {
        "resolved_model_prefix": "anthropic",
        "resolved_route": "/v1/messages",
        "route_source": "litellm_adapter_resolution",
        "wire_route_observed": False,
    }
    assert resolved_transport(
        "anthropic/claude-opus-5-5",
        "https://gateway-central.ai.private.hackerrank.link",
    )["resolved_endpoint"] == "https://gateway-central.ai.private.hackerrank.link/v1/messages"
    assert gateway_transport_base_url(
        "https://gateway-central.ai.private.hackerrank.link/v1",
        "anthropic/claude-opus-5-5",
    ) == "https://gateway-central.ai.private.hackerrank.link"
    assert gateway_transport_base_url(
        "https://gateway-central.ai.private.hackerrank.link/v1",
        "openai/claude-opus-5-5",
    ) == "https://gateway-central.ai.private.hackerrank.link/v1"


def test_opus_5_5_registers_adaptive_thinking_capabilities(monkeypatch):
    captured = {}
    fake_litellm = SimpleNamespace(register_model=lambda payload, **kwargs: captured.update(payload=payload, kwargs=kwargs))
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    harness.register_gateway_model_capabilities("anthropic/claude-opus-5-5")

    capabilities = captured["payload"]["claude-opus-5-5"]
    assert capabilities["supports_adaptive_thinking"] is True
    assert capabilities["supports_output_config"] is True
    assert capabilities["max_output_tokens"] == 128_000
    assert captured["kwargs"] == {"persist_across_reloads": False}


def test_empty_length_response_gets_a_focused_next_turn():
    response = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": None, "tool_calls": None},
            }
        ]
    }
    llm = SimpleNamespace()

    assert harness._is_empty_length_response(response)
    harness._remember_output_limit(response, llm)
    recovered = harness._apply_output_limit_recovery(llm, [{"role": "user", "content": "original"}])

    assert recovered[-1]["role"] == "user"
    assert "exactly one small concrete action" in recovered[-1]["content"]
    assert harness._apply_output_limit_recovery(llm, recovered) is recovered


def test_counts_consecutive_empty_length_responses(tmp_path):
    capture = tmp_path / "gateway_responses.jsonl"
    normal = {"response": {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{}]}}]}}
    truncated = {"response": {"choices": [{"finish_reason": "length", "message": {"content": "", "tool_calls": None}}]}}
    capture.write_text(
        "\n".join(json.dumps(record) for record in [normal, truncated, truncated]) + "\n",
        encoding="utf-8",
    )

    assert harness._empty_length_tail(capture) == 2
    workspace = {"status": "available", "files": {"total_changed": 0}}
    assert "consecutive empty responses" in harness._incomplete_run_reason(capture, workspace)

    capture.write_text(json.dumps(normal) + "\n", encoding="utf-8")
    assert harness._incomplete_run_reason(capture, workspace) == (
        "OpenHands stopped without changing the candidate workspace"
    )
    workspace["files"]["total_changed"] = 1
    assert harness._incomplete_run_reason(capture, workspace) is None


def test_preserves_gemini_thought_signature_across_tool_turns():
    llm = SimpleNamespace(model="openai/gemini-3.7-flash")
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            id="call_terminal",
                            extra_content={"google": {"thought_signature": "sig-123"}},
                        )
                    ]
                )
            )
        ]
    )
    _remember_gemini_signatures(llm, response)

    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": "{}"},
                }
            ],
        }
    ]
    restored = _restore_gemini_signatures(llm, messages)

    assert restored[0]["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "sig-123"}
    }


def test_restores_gemini_signature_when_openhands_rewrites_tool_call_id():
    llm = SimpleNamespace(model="openai/gemini-3.7-flash")
    response = {
        "choices": [{
            "message": {
                "tool_calls": [{
                    "id": "provider-call",
                    "function": {"name": "terminal", "arguments": '{"command":"pwd"}'},
                    "extra_content": {"google": {"thought_signature": "sig-remapped"}},
                }]
            }
        }]
    }
    _remember_gemini_signatures(llm, response)

    restored = _restore_gemini_signatures(llm, [{
        "role": "assistant",
        "tool_calls": [{
            "id": "openhands-call",
            "function": {"name": "terminal", "arguments": '{"command": "pwd"}'},
        }],
    }])

    assert restored[0]["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "sig-remapped"}
    }


def test_refreshing_reused_gemini_tool_call_id_prevents_lru_eviction():
    llm = SimpleNamespace(model="openai/gemini-3.7-flash")

    def remember(call_id, signature):
        _remember_gemini_signatures(llm, {
            "choices": [{"message": {"tool_calls": [{
                "id": call_id,
                "function": {"name": "terminal", "arguments": "{}"},
                "extra_content": {"google": {"thought_signature": signature}},
            }]}}]
        })

    remember("reused-call", "old-signature")
    for index in range(256):
        remember(f"call-{index}", f"signature-{index}")
    remember("reused-call", "fresh-signature")
    remember("overflow", "overflow-signature")

    signatures = llm._astra_gemini_thought_signatures
    assert signatures["reused-call"] == "fresh-signature"
    assert "call-0" not in signatures


def test_prunes_gemini_tool_history_when_signature_cannot_be_recovered():
    llm = SimpleNamespace(model="openai/gemini-3.7-flash")
    messages = [
        {
            "role": "assistant",
            "tool_calls": [{
                "id": "lost-call",
                "function": {"name": "terminal", "arguments": '{"command":"pwd"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "lost-call", "content": "output"},
        {"role": "user", "content": "continue"},
    ]

    with pytest.warns(RuntimeWarning, match="unavailable thought signatures"):
        restored = _restore_gemini_signatures(llm, messages)

    assert restored == [{"role": "user", "content": "continue"}]


def test_pruning_reused_tool_call_id_keeps_the_earlier_valid_tool_result():
    llm = SimpleNamespace(model="openai/gemini-3.7-flash")
    signature = {"google": {"thought_signature": "sig-valid"}}
    messages = [
        {
            "role": "assistant",
            "tool_calls": [{
                "id": "reused-call",
                "function": {"name": "terminal", "arguments": '{"command":"first"}'},
                "extra_content": signature,
            }],
        },
        {"role": "tool", "tool_call_id": "reused-call", "content": "first result"},
        {
            "role": "assistant",
            "tool_calls": [{
                "id": "reused-call",
                "function": {"name": "terminal", "arguments": '{"command":"second"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "reused-call", "content": "second result"},
    ]

    with pytest.warns(RuntimeWarning, match="unavailable thought signatures"):
        restored = _restore_gemini_signatures(llm, messages)

    assert restored == messages[:2]


def test_does_not_modify_non_gemini_messages():
    llm = SimpleNamespace(model="openai/grok-4.5")
    messages = [{"role": "assistant", "tool_calls": [{"id": "call_1"}]}]

    assert _restore_gemini_signatures(llm, messages) is messages


def test_normalizes_empty_tool_call_arguments_and_reports_validation():
    messages, diagnostics = _normalize_and_validate_messages([
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call-empty", "type": "function", "function": {"name": "terminal", "arguments": ""}},
                {"id": "call-object", "type": "function", "function": {"name": "terminal", "arguments": {"command": "pwd"}}},
            ],
        }
    ])

    calls = messages[0]["tool_calls"]
    assert calls[0]["function"]["arguments"] == "{}"
    assert calls[1]["function"]["arguments"] == '{"command":"pwd"}'
    assert diagnostics == {
        "message_count": 1,
        "tool_call_count": 2,
        "normalized_empty_argument_count": 1,
        "orphaned_tool_call_count": 0,
        "orphaned_tool_call_ids": [],
    }


def test_reports_interior_orphaned_tool_call_but_not_trailing_one():
    # msg 1 declares a tool call that is never answered anywhere (interior gap) before
    # the next assistant turn (msg 3) starts; msg 3's own tool call is trailing/unanswered
    # because it is the last message, which is expected and must not be flagged.
    messages, diagnostics = _normalize_and_validate_messages([
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "call-orphan", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call-unrelated", "content": "done"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "call-trailing", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}],
        },
    ])

    assert diagnostics["orphaned_tool_call_count"] == 1
    assert diagnostics["orphaned_tool_call_ids"] == ["call-orphan"]


def test_reports_all_trailing_tool_calls_as_not_orphaned():
    # Both tool calls belong to the final message, so neither counts as an interior gap.
    messages, diagnostics = _normalize_and_validate_messages([
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call-a", "type": "function", "function": {"name": "terminal", "arguments": "{}"}},
                {"id": "call-b", "type": "function", "function": {"name": "terminal", "arguments": "{}"}},
            ],
        },
    ])

    assert diagnostics["orphaned_tool_call_count"] == 0
    assert diagnostics["orphaned_tool_call_ids"] == []


def test_rejects_malformed_tool_call_arguments_before_gateway_request():
    with pytest.raises(ValueError, match=r"messages\[0\]\.tool_calls\[0\]\.function\.arguments"):
        _normalize_and_validate_messages([
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call-invalid", "type": "function", "function": {"name": "terminal", "arguments": "{not-json"}},
                ],
            }
        ])


def test_collects_tokens_and_missing_cost(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps({"type": "openhands_event", "tool_name": "terminal"}) + "\n"
        + json.dumps({"type": "openhands_metrics", "input_tokens": 10, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 5, "output_tokens": 4}) + "\n",
        encoding="utf-8",
    )
    manifest = collect(events, tmp_path / "telemetry.json", model="openai/gemini-3.7-flash", reasoning="medium", started_at="start", completed_at="end", status="completed", exit_code=0)
    assert manifest["usage"]["total_tokens"] == 14
    assert manifest["cost"]["gateway"]["status"] == "unavailable"
    assert manifest["cost"]["openhands"]["status"] == "unavailable"
    assert manifest["tools"]["by_tool"] == {"terminal": 1}


def test_collects_gateway_and_openhands_costs_separately(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps({"type": "openhands_metrics", "cost_usd": 1.25}) + "\n",
        encoding="utf-8",
    )
    gateway_responses = tmp_path / "gateway_responses.jsonl"
    gateway_responses.write_text(
        json.dumps({"type": "gateway_response", "status": "ok", "latency_ms": 100, "response": {"usage": {"cost": 0.1}}}) + "\n"
        + json.dumps({"type": "gateway_response", "status": "ok", "latency_ms": 250, "response": {"usage": {"cost": 0.2}}}) + "\n"
        + json.dumps({"type": "gateway_response", "status": "ok", "response": {"usage": {}}}) + "\n",
        encoding="utf-8",
    )

    manifest = collect(
        events,
        tmp_path / "telemetry.json",
        model="openai/gemini-3.7-flash",
        reasoning="low",
        started_at="start",
        completed_at="end",
        status="completed",
        exit_code=0,
        gateway_responses_path=gateway_responses,
    )

    assert manifest["cost"]["gateway"]["amount_usd"] == pytest.approx(0.3)
    assert manifest["cost"]["gateway"]["responses_with_cost"] == 2
    assert manifest["cost"]["openhands"]["amount_usd"] == 1.25
    assert manifest["cost"]["custom_estimation"]["status"] == "unavailable"
    assert manifest["cost"]["custom_estimation"]["reason"] == "token_usage_unavailable"
    assert manifest["timing"]["llm_requests"] == {
        "count": 3,
        "with_latency": 2,
        "successful": 3,
        "failed": 0,
        "total_latency_ms": 350.0,
        "average_latency_ms": 175.0,
        "min_latency_ms": 100.0,
        "max_latency_ms": 250.0,
    }


def test_custom_estimation_sums_gateway_usage_when_costs_are_missing(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps({
            "type": "openhands_metrics",
            "input_tokens": 999,
            "output_tokens": 999,
        }) + "\n",
        encoding="utf-8",
    )
    gateway_responses = tmp_path / "gateway_responses.jsonl"
    gateway_responses.write_text(
        json.dumps({
            "status": "ok",
            "response": {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 10}},
        }) + "\n"
        + json.dumps({
            "status": "ok",
            "response": {"usage": {"prompt_tokens": 50, "completion_tokens": 5}},
        }) + "\n",
        encoding="utf-8",
    )

    manifest = collect(
        events,
        tmp_path / "telemetry.json",
        model="openai/gpt-5.6-luna",
        reasoning="low",
        started_at="start",
        completed_at="end",
        status="completed",
        exit_code=0,
        gateway_responses_path=gateway_responses,
    )

    estimate = manifest["cost"]["custom_estimation"]
    assert estimate["status"] == "estimated"
    assert estimate["usage_source"] == "gateway_usage"
    assert estimate["requests"] == 2
    assert estimate["requests_with_usage"] == 2
    assert estimate["amount_usd"] == pytest.approx(0.0000582)


def test_custom_estimation_is_independent_of_reported_costs(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps({
            "type": "openhands_metrics",
            "input_tokens": 10,
            "output_tokens": 4,
            "cost_usd": 1.0,
        }) + "\n",
        encoding="utf-8",
    )
    gateway_responses = tmp_path / "gateway_responses.jsonl"
    gateway_responses.write_text(
        json.dumps({
            "status": "ok",
            "response": {"usage": {"prompt_tokens": 20, "completion_tokens": 5, "cost": 0.1}},
        }) + "\n",
        encoding="utf-8",
    )

    manifest = collect(
        events,
        tmp_path / "telemetry.json",
        model="openai/gpt-5.6-luna",
        reasoning="low",
        started_at="start",
        completed_at="end",
        status="completed",
        exit_code=0,
        gateway_responses_path=gateway_responses,
    )

    assert manifest["cost"]["gateway"]["amount_usd"] == pytest.approx(0.1)
    assert manifest["cost"]["openhands"]["amount_usd"] == pytest.approx(1.0)
    assert manifest["cost"]["custom_estimation"]["status"] == "estimated"
    assert manifest["cost"]["custom_estimation"]["usage_source"] == "gateway_usage"
    assert manifest["cost"]["custom_estimation"]["amount_usd"] == pytest.approx(0.00001)


def test_custom_estimation_handles_unknown_and_unpriced_models_gracefully():
    assert normalize_model_name("openai/gpt-5.6-luna") == "gpt-5.6-luna"
    assert len(MASTER_MODEL_NAMES) == 14

    unknown = estimate_custom_cost(
        "gateway/not-in-the-master-list",
        openhands_usage={"input_tokens": 10, "output_tokens": 4},
    )
    assert unknown["status"] == "unavailable"
    assert unknown["reason"] == "model_not_in_pricing_master_list"

    assert all(spec.configured for spec in PRICING_TABLE.values())


def test_pricing_master_list_is_json_and_versioned():
    pricing_path = Path(__file__).parents[1] / "src" / "hackerrank_openhands" / "pricing.json"
    pricing_document = json.loads(pricing_path.read_text(encoding="utf-8"))

    assert pricing_document["schema_version"] == 1
    assert tuple(pricing_document["models"]) == MASTER_MODEL_NAMES
    assert set(pricing_document["models"]) == set(MASTER_MODEL_NAMES)


def test_grok_pricing_uses_xai_short_and_long_context_rates():
    short = estimate_custom_cost(
        "openai/grok-4.5",
        openhands_usage={"input_tokens": 100, "output_tokens": 10},
    )
    assert short["amount_usd"] == pytest.approx(0.00026)
    assert short["status"] == "estimated"

    long = estimate_custom_cost(
        "openai/grok-4.6",
        openhands_usage={"input_tokens": 200_000, "output_tokens": 10},
    )
    assert long["amount_usd"] == pytest.approx(0.80012)
    assert long["pricing"]["long_context_threshold_tokens"] == 200_000


def test_official_master_pricing_entries_are_present():
    expected = {
        "claude-fable-5": (10.0, 50.0, 1.0),
        "claude-opus-5": (5.0, 25.0, 0.5),
        "claude-sonnet-5": (2.0, 10.0, 0.2),
        "kimi-k3": (3.0, 15.0, 0.3),
        "minimax-m3": (0.6, 2.4, 0.12),
        "qwen-3.8": (2.0, 6.0, None),
        "deepseek-v4-pro": (0.66, 1.98, 0.022),
        "glm-5.2": (1.4, 4.4, 0.26),
    }
    for model, rates in expected.items():
        spec = PRICING_TABLE[model]
        assert (spec.input_usd_per_million, spec.output_usd_per_million, spec.cache_read_usd_per_million) == rates


def test_prefers_complete_gateway_total_tokens(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps({
            "type": "openhands_metrics",
            "input_tokens": 10,
            "cache_read_input_tokens": 20,
            "output_tokens": 4,
        }) + "\n",
        encoding="utf-8",
    )
    gateway_responses = tmp_path / "gateway_responses.jsonl"
    gateway_responses.write_text(
        json.dumps({"status": "ok", "response": {"usage": {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40}}}) + "\n"
        + json.dumps({"status": "ok", "response": {"usage": {"input_tokens": 40, "output_tokens": 19, "total_tokens": 59}}}) + "\n",
        encoding="utf-8",
    )

    manifest = collect(
        events,
        tmp_path / "telemetry.json",
        model="openai/gpt-5.6-luna",
        reasoning="low",
        started_at="start",
        completed_at="end",
        status="completed",
        exit_code=0,
        gateway_responses_path=gateway_responses,
    )

    assert manifest["usage"] == {
        "source": "gateway",
        "requests": 2,
        "input_tokens": 70,
        "cached_input_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 29,
        "reasoning_tokens": 0,
        "total_tokens": 99,
    }


def test_nested_gateway_usage_is_normalized_and_preferred(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps({"type": "openhands_metrics", "input_tokens": 999, "output_tokens": 999}) + "\n",
        encoding="utf-8",
    )
    gateway_responses = tmp_path / "gateway_responses.jsonl"
    gateway_responses.write_text(
        json.dumps({
            "status": "ok",
            "response": {
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 5},
                    "output_tokens": 20,
                    "output_tokens_details": {"reasoning_tokens": 7},
                    "total_tokens": 120,
                }
            },
        }) + "\n",
        encoding="utf-8",
    )

    manifest = collect(
        events,
        tmp_path / "telemetry.json",
        model="openai/gpt-5.6-luna",
        reasoning="low",
        started_at="start",
        completed_at="end",
        status="completed",
        exit_code=0,
        gateway_responses_path=gateway_responses,
    )

    assert manifest["usage"] == {
        "source": "gateway",
        "requests": 1,
        "input_tokens": 100,
        "cached_input_tokens": 15,
        "cache_read_tokens": 10,
        "cache_write_tokens": 5,
        "output_tokens": 20,
        "reasoning_tokens": 7,
        "total_tokens": 120,
    }
    assert manifest["cost"]["custom_estimation"]["usage_source"] == "gateway_usage"
    assert manifest["cost"]["custom_estimation"]["amount_usd"] == pytest.approx(0.00004245)


def test_gemini_gateway_fix_removes_cache_key_sync_and_async(monkeypatch):
    from openhands.sdk import LLM

    sync_calls = []
    async_calls = []

    def original_sync(self, *, messages, **kwargs):
        sync_calls.append((messages, kwargs))
        return "sync-ok"

    async def original_async(self, *, messages, **kwargs):
        async_calls.append((messages, kwargs))
        return "async-ok"

    def original_responses(self, *args, **kwargs):
        return "responses-ok"

    async def original_aresponses(self, *args, **kwargs):
        return "aresponses-ok"

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    monkeypatch.setattr(LLM, "_atransport_call", original_async)
    monkeypatch.setattr(LLM, "responses", original_responses)
    monkeypatch.setattr(LLM, "aresponses", original_aresponses)
    harness.install_gateway_fix("http://gateway-internal-nlb.ai.hackerrank.com/v1")
    client = type("Client", (), {"model": "openai/gemini-3.7-flash"})()
    messages = [{"role": "user", "content": "hello", "name": "rejected", "refusal": "rejected"}]

    assert LLM._transport_call(
        client,
        messages=messages,
        prompt_cache_key="top-level-secret",
        extra_body={"prompt_cache_key": "nested-secret", "temperature": 0},
    ) == "sync-ok"
    assert asyncio.run(LLM._atransport_call(
        client,
        messages=messages,
        prompt_cache_key="top-level-secret",
        extra_body={"prompt_cache_key": "nested-secret", "temperature": 0},
    )) == "async-ok"

    for calls in (sync_calls, async_calls):
        sent_messages, kwargs = calls[0]
        assert sent_messages == [{"role": "user", "content": "hello"}]
        assert "prompt_cache_key" not in kwargs
        assert kwargs["extra_body"] == {"temperature": 0}
        assert kwargs.get("stream") is not True
        assert kwargs.get("enable_streaming") is not True


def test_gateway_fix_normalizes_tool_arguments_before_transport(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    sent = []

    def original_sync(self, *, messages, **kwargs):
        sent.append(messages)
        return "sync-ok"

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/gpt-5.6-luna", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()
    messages = [{
        "role": "assistant",
        "tool_calls": [{
            "id": "call-empty",
            "type": "function",
            "function": {"name": "terminal", "arguments": ""},
        }],
    }]

    with harness.capture_gateway_responses(capture_path):
        assert LLM._transport_call(client, messages=messages) == "sync-ok"

    assert sent[0][0]["tool_calls"][0]["function"]["arguments"] == "{}"
    record = json.loads(capture_path.read_text(encoding="utf-8"))
    assert record["request_validation"] == {
        "message_count": 1,
        "tool_call_count": 1,
        "normalized_empty_argument_count": 1,
        "orphaned_tool_call_count": 0,
        "orphaned_tool_call_ids": [],
    }


def test_claude_messages_transport_injects_cache_control_and_records_route(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    sent = []

    def original_sync(self, *, messages, **kwargs):
        sent.append((messages, kwargs))
        return "sync-ok"

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "anthropic/claude-opus-5-5", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        assert LLM._transport_call(
            client,
            messages=[{"role": "system", "content": "stable system prompt"}, {"role": "user", "content": "hello"}],
            enable_streaming=False,
        ) == "sync-ok"

    messages, kwargs = sent[0]
    assert messages[0]["content"] == [{"type": "text", "text": "stable system prompt", "cache_control": {"type": "ephemeral"}}]
    assert kwargs["stream"] is True
    assert kwargs["enable_streaming"] is True
    assert callable(kwargs["on_token"])
    record = json.loads(capture_path.read_text(encoding="utf-8"))
    assert record["transport"]["resolved_route"] == "/v1/messages"
    assert record["transport"]["resolved_model_prefix"] == "anthropic"


def test_enable_anthropic_messages_streaming_overwrites_openhands_fallback_and_keeps_real_callbacks():
    kwargs = {"enable_streaming": False, "on_token": None, "temperature": 0}
    _enable_anthropic_messages_streaming(kwargs)
    assert kwargs["stream"] is True
    assert kwargs["enable_streaming"] is True
    assert kwargs["temperature"] == 0
    assert kwargs["on_token"] is not None
    assert callable(kwargs["on_token"])

    seen = []

    def marker(chunk):
        seen.append(chunk)

    kwargs_with_callback = {"stream": False, "enable_streaming": False, "on_token": marker}
    _enable_anthropic_messages_streaming(kwargs_with_callback)
    assert kwargs_with_callback["on_token"] is marker
    kwargs_with_callback["on_token"]("delta")
    assert seen == ["delta"]


def _install_anthropic_transport_spies(monkeypatch):
    """Wrap a fresh gateway fix around spies that match OpenHands's real signature.

    OpenHands's ``_transport_call`` takes ``enable_streaming`` and ``on_token`` as
    named parameters, not as a generic kwargs bag. Spies must use that shape so a
    regression that only sets ``kwargs['stream']`` still fails the test.
    """
    from openhands.sdk import LLM

    sent = []

    def original_sync(self, *, messages, enable_streaming=False, on_token=None, **kwargs):
        sent.append({
            "path": "sync",
            "messages": messages,
            "enable_streaming": enable_streaming,
            "on_token": on_token,
            "stream": kwargs.get("stream"),
            "kwargs": kwargs,
        })
        return "sync-ok"

    async def original_async(self, *, messages, enable_streaming=False, on_token=None, **kwargs):
        sent.append({
            "path": "async",
            "messages": messages,
            "enable_streaming": enable_streaming,
            "on_token": on_token,
            "stream": kwargs.get("stream"),
            "kwargs": kwargs,
        })
        return "async-ok"

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    monkeypatch.setattr(LLM, "_atransport_call", original_async)
    monkeypatch.setattr(LLM, "responses", lambda self, *args, **kwargs: "responses-ok")
    monkeypatch.setattr(LLM, "aresponses", lambda self, *args, **kwargs: "aresponses-ok")
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    return sent


def test_anthropic_streaming_survives_openhands_missing_on_token_fallback(monkeypatch):
    """Reproduce OpenHands completion(): stream=True + no on_token disables streaming.

    That is the production call shape for a prompt-caching Claude run. The
    Gateway patch must restore stream/enable_streaming and supply a drain
    callback so LiteLLM's Anthropic adapter sends ``stream: true``.
    """
    from openhands.sdk import LLM

    sent = _install_anthropic_transport_spies(monkeypatch)
    client = type("Client", (), {"model": "anthropic/claude-sonnet-5"})()
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]

    # Copied from openhands.sdk.llm.llm.LLM.completion(): streaming is requested
    # (LLM.stream=True for prompt-caching) but no on_token is wired, so the SDK
    # pops stream and calls transport with enable_streaming=False.
    call_kwargs = {}
    llm_stream = True
    on_token = None
    enable_streaming = bool(call_kwargs.get("stream", False)) or llm_stream
    if enable_streaming and on_token is None:
        enable_streaming = False
        call_kwargs.pop("stream", None)

    assert enable_streaming is False
    assert "stream" not in call_kwargs

    assert LLM._transport_call(
        client,
        messages=messages,
        enable_streaming=enable_streaming,
        on_token=on_token,
        **call_kwargs,
    ) == "sync-ok"
    assert asyncio.run(LLM._atransport_call(
        client,
        messages=messages,
        enable_streaming=enable_streaming,
        on_token=on_token,
        **call_kwargs,
    )) == "async-ok"

    assert [item["path"] for item in sent] == ["sync", "async"]
    for item in sent:
        assert item["enable_streaming"] is True
        assert item["stream"] is True
        assert item["on_token"] is not None
        assert callable(item["on_token"])
        assert item["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_anthropic_streaming_keeps_caller_on_token(monkeypatch):
    from openhands.sdk import LLM

    sent = _install_anthropic_transport_spies(monkeypatch)
    client = type("Client", (), {"model": "anthropic/claude-opus-5-5"})()
    seen = []

    def marker(chunk):
        seen.append(chunk)

    LLM._transport_call(
        client,
        messages=[{"role": "user", "content": "hi"}],
        enable_streaming=True,
        on_token=marker,
        stream=True,
    )
    assert sent[0]["on_token"] is marker
    sent[0]["on_token"]("chunk")
    assert seen == ["chunk"]


def test_openai_compatible_claude_does_not_force_streaming(monkeypatch):
    from openhands.sdk import LLM

    sent = _install_anthropic_transport_spies(monkeypatch)
    client = type("Client", (), {"model": "openai/claude-opus-5-5"})()

    LLM._transport_call(
        client,
        messages=[{"role": "user", "content": "hi"}],
        enable_streaming=False,
        on_token=None,
    )
    assert sent[0]["enable_streaming"] is False
    assert sent[0]["stream"] is None
    assert sent[0]["on_token"] is None


def test_gateway_response_capture_is_separate_and_sanitized(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    def make_response(client):
        return SimpleNamespace(
            model_dump=lambda mode="python": {
                "id": "response-1",
                "model": client.model,
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                    "prompt_tokens_details": {"cached_tokens": 2},
                    "cost": 0.000003,
                },
                "choices": [],
                "api_key": "secret-value",
            },
            _hidden_params={"additional_headers": {"Authorization": "Bearer secret-value", "x-request-id": "request-1"}},
        )

    def original_sync(self, *, messages, **kwargs):
        return make_response(self)

    def original_responses(self, *args, **kwargs):
        return SimpleNamespace(raw_response=make_response(self))

    async def original_aresponses(self, *args, **kwargs):
        return SimpleNamespace(raw_response=make_response(self))

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    monkeypatch.setattr(LLM, "_atransport_call", original_sync)
    monkeypatch.setattr(LLM, "responses", original_responses)
    monkeypatch.setattr(LLM, "aresponses", original_aresponses)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/gpt-5.6-luna", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        response = LLM._transport_call(client, messages=[{"role": "user", "content": "hello"}])
        LLM.responses(client)

    assert response.model_dump()["usage"]["cost"] == 0.000003
    records = [json.loads(line) for line in capture_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["type"] == "gateway_response"
    assert records[0]["status"] == "ok"
    assert records[0]["response"]["usage"]["prompt_tokens"] == 10
    assert records[0]["response"]["usage"]["prompt_tokens_details"]["cached_tokens"] == 2
    assert records[0]["response"]["usage"]["cost"] == 0.000003
    assert isinstance(records[0]["latency_ms"], float)
    assert records[0]["latency_ms"] >= 0
    assert records[0]["response"]["api_key"] == "[REDACTED]"
    assert records[0]["hidden_params"]["additional_headers"]["Authorization"] == "[REDACTED]"


def test_gateway_response_capture_failure_does_not_change_llm_error(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    def original_sync(self, *, messages, **kwargs):
        raise RuntimeError("Gateway unavailable")

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    monkeypatch.setattr(LLM, "_atransport_call", original_sync)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/gpt-5.6-luna", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        with pytest.raises(RuntimeError, match="Gateway unavailable"):
            LLM._transport_call(client, messages=[])

    record = json.loads(capture_path.read_text(encoding="utf-8"))
    assert record["status"] == "error"
    assert record["error"] == {"type": "RuntimeError", "message": "Gateway unavailable"}
    assert record["request"]["method"] == "POST"
    assert record["request"]["url_path"] == "/v1"
    assert record["request"]["body_scope"] == "redacted_logical_payload_at_litellm_boundary"
    assert len(record["request"]["body_sha256"]) == 64
    assert record["request"]["wire_body_observed"] is False


def test_gateway_response_capture_records_safe_http_failure_diagnostics(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    class GatewayError(Exception):
        def __init__(self):
            super().__init__("invalid_body")
            self.response = SimpleNamespace(
                status_code=400,
                headers={"x-request-id": "req-123", "content-type": "application/json"},
                text='{"message":"could not read request body","api_key":"should-not-appear"}',
            )

    def original_sync(self, *, messages, **kwargs):
        raise GatewayError()

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/gpt-5.6-sol", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        with pytest.raises(GatewayError):
            LLM._transport_call(client, messages=[{"role": "user", "content": "hello"}], headers={"content-type": "application/json"})

    record = json.loads(capture_path.read_text(encoding="utf-8"))
    assert record["status_code"] == 400
    assert record["request_id"] == "req-123"
    assert record["error_body"] == '{"message":"could not read request body","api_key":"[REDACTED]"}'
    assert record["request"]["framing_headers"]["content-type"] == "application/json"


def _invalid_body_error() -> Exception:
    error = Exception("litellm.BadRequestError: OpenAIException - request body must be valid JSON")
    error.response = SimpleNamespace(
        status_code=400,
        headers={},
        text='{"message":"request body must be valid JSON","type":"invalid_request_error","code":"invalid_body"}',
    )
    return error


def test_is_transient_invalid_body_error_matches_only_that_signature():
    from hackerrank_openhands.harness import _is_transient_invalid_body_error

    assert _is_transient_invalid_body_error(_invalid_body_error()) is True

    other_400 = Exception("nope")
    other_400.response = SimpleNamespace(status_code=400, headers={}, text='{"message":"model_not_allowed"}')
    assert _is_transient_invalid_body_error(other_400) is False

    not_400 = Exception("server error")
    not_400.response = SimpleNamespace(status_code=500, headers={}, text="")
    assert _is_transient_invalid_body_error(not_400) is False


def _bad_gateway_error() -> Exception:
    error = Exception("litellm.BadGatewayError: BadGatewayError: OpenAIException - all candidate providers failed")
    error.response = SimpleNamespace(status_code=502, headers={}, text="")
    return error


def test_is_transient_bad_gateway_error_matches_only_that_signature():
    from hackerrank_openhands.harness import _is_transient_bad_gateway_error

    assert _is_transient_bad_gateway_error(_bad_gateway_error()) is True

    other_502 = Exception("upstream connect error")
    other_502.response = SimpleNamespace(status_code=502, headers={}, text="")
    assert _is_transient_bad_gateway_error(other_502) is False

    not_502 = Exception("all candidate providers failed")
    not_502.response = SimpleNamespace(status_code=400, headers={}, text="")
    # The distinctive phrase alone is enough, regardless of status code, since some
    # error wrappers do not expose a usable response.status_code at all.
    assert _is_transient_bad_gateway_error(not_502) is True

    unrelated = Exception("server error")
    unrelated.response = SimpleNamespace(status_code=500, headers={}, text="")
    assert _is_transient_bad_gateway_error(unrelated) is False


def test_gateway_fix_retries_transient_bad_gateway_after_a_long_delay(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    calls = []
    delays = []

    def original_sync(self, *, messages, **kwargs):
        calls.append(1)
        if len(calls) < 4:
            raise _bad_gateway_error()
        return "sync-ok"

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    monkeypatch.setattr(harness.time, "sleep", lambda seconds: delays.append(seconds))
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/qwen-3.8", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        result = LLM._transport_call(client, messages=[{"role": "user", "content": "hi"}])

    assert result == "sync-ok"
    assert len(calls) == 4
    # Escalating delay: 120s, then 240s, then 360s -- not a fixed interval.
    assert delays == [120.0, 240.0, 360.0]
    records = [json.loads(line) for line in capture_path.read_text(encoding="utf-8").splitlines()]
    assert [record["status"] for record in records] == ["error", "error", "error", "ok"]


def test_gateway_fix_stops_retrying_bad_gateway_after_three_retries(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    calls = []

    def original_sync(self, *, messages, **kwargs):
        calls.append(1)
        raise _bad_gateway_error()

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    monkeypatch.setattr(harness.time, "sleep", lambda seconds: None)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/qwen-3.8", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        with pytest.raises(Exception, match="all candidate providers failed"):
            LLM._transport_call(client, messages=[{"role": "user", "content": "hi"}])

    # _BAD_GATEWAY_MAX_ATTEMPTS caps this at exactly 3 retries (4 attempts total),
    # not unbounded ones.
    assert len(calls) == harness._BAD_GATEWAY_MAX_ATTEMPTS == 4


def test_gateway_fix_retries_transient_invalid_body_and_then_succeeds(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    calls = []

    def original_sync(self, *, messages, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise _invalid_body_error()
        return "sync-ok"

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    monkeypatch.setattr(harness.time, "sleep", lambda seconds: None)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/minimax-m3", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        result = LLM._transport_call(client, messages=[{"role": "user", "content": "hi"}])

    assert result == "sync-ok"
    assert len(calls) == 3
    records = [json.loads(line) for line in capture_path.read_text(encoding="utf-8").splitlines()]
    assert [record["status"] for record in records] == ["error", "error", "ok"]


def test_stuck_request_circuit_breaker_blocks_after_repeated_identical_failures(monkeypatch, tmp_path):
    # Reproduces what was observed live: the same request, byte-for-byte, failing
    # (there, a Timeout) again and again with the agent retrying the identical turn
    # each time. Nothing here controls whether the agent retries -- only whether we
    # let it keep hitting the network for a request already proven not to work.
    from openhands.sdk import LLM

    calls = []

    def original_sync(self, *, messages, **kwargs):
        calls.append(1)
        raise RuntimeError("Timeout: request timed out")

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/claude-opus-5", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()
    messages = [{"role": "user", "content": "hi"}]

    with harness.capture_gateway_responses(capture_path):
        # First two attempts reach the network and fail, exactly like a real repeat.
        for _ in range(harness._STUCK_REQUEST_MAX_CONSECUTIVE_FAILURES):
            with pytest.raises(RuntimeError, match="Timeout"):
                LLM._transport_call(client, messages=messages)
        assert len(calls) == harness._STUCK_REQUEST_MAX_CONSECUTIVE_FAILURES

        # The next identical attempt must not reach the network at all.
        with pytest.raises(harness.StuckRequestError, match="already failed"):
            LLM._transport_call(client, messages=messages)
        assert len(calls) == harness._STUCK_REQUEST_MAX_CONSECUTIVE_FAILURES

    records = [json.loads(line) for line in capture_path.read_text(encoding="utf-8").splitlines()]
    assert [record["status"] for record in records] == ["error", "error", "error"]
    assert "StuckRequestError" in records[-1]["error"]["type"]


def test_stuck_request_circuit_breaker_ignores_a_different_request(monkeypatch, tmp_path):
    # Two failures of request A must not trip the breaker for an unrelated request B.
    from openhands.sdk import LLM

    def original_sync(self, *, messages, **kwargs):
        raise RuntimeError("Timeout: request timed out")

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/claude-opus-5", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        for _ in range(harness._STUCK_REQUEST_MAX_CONSECUTIVE_FAILURES):
            with pytest.raises(RuntimeError, match="Timeout"):
                LLM._transport_call(client, messages=[{"role": "user", "content": "request A"}])
        # A different request must still reach the network, not be blocked as "stuck".
        with pytest.raises(RuntimeError, match="Timeout"):
            LLM._transport_call(client, messages=[{"role": "user", "content": "request B"}])


def test_stuck_request_circuit_breaker_resets_after_a_success(monkeypatch, tmp_path):
    # A later success for the same content means it is no longer stuck, so a fresh
    # failure afterward must start counting from zero again, not stay tripped.
    from openhands.sdk import LLM

    calls = []

    def original_sync(self, *, messages, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            return "sync-ok"
        raise RuntimeError("Timeout: request timed out")

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/claude-opus-5", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()
    messages = [{"role": "user", "content": "hi"}]

    with harness.capture_gateway_responses(capture_path):
        with pytest.raises(RuntimeError, match="Timeout"):
            LLM._transport_call(client, messages=messages)  # call 1: fails
        assert LLM._transport_call(client, messages=messages) == "sync-ok"  # call 2: succeeds, clears the count
        with pytest.raises(RuntimeError, match="Timeout"):
            LLM._transport_call(client, messages=messages)  # call 3: fails once more, not yet tripped
    assert len(calls) == 3


def test_gateway_fix_gives_up_after_max_attempts_on_persistent_invalid_body(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    calls = []

    def original_sync(self, *, messages, **kwargs):
        calls.append(1)
        raise _invalid_body_error()

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    monkeypatch.setattr(harness.time, "sleep", lambda seconds: None)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/minimax-m3", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        with pytest.raises(Exception, match="request body must be valid JSON"):
            LLM._transport_call(client, messages=[{"role": "user", "content": "hi"}])

    assert len(calls) == harness._INVALID_BODY_MAX_ATTEMPTS


def test_gateway_fix_does_not_retry_non_transient_400(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    calls = []

    def original_sync(self, *, messages, **kwargs):
        calls.append(1)
        error = Exception("model_not_allowed")
        error.response = SimpleNamespace(status_code=400, headers={}, text='{"message":"model_not_allowed"}')
        raise error

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    monkeypatch.setattr(harness.time, "sleep", lambda seconds: (_ for _ in ()).throw(AssertionError("must not sleep/retry for a non-transient error")))
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/minimax-m3", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        with pytest.raises(Exception, match="model_not_allowed"):
            LLM._transport_call(client, messages=[{"role": "user", "content": "hi"}])

    assert len(calls) == 1


def test_gateway_fix_retries_transient_invalid_body_on_async_path(monkeypatch, tmp_path):
    from openhands.sdk import LLM

    calls = []

    async def original_async(self, *, messages, **kwargs):
        calls.append(1)
        if len(calls) < 2:
            raise _invalid_body_error()
        return "async-ok"

    async def noop_sleep(seconds):
        return None

    monkeypatch.setattr(LLM, "_atransport_call", original_async)
    monkeypatch.setattr(harness.asyncio, "sleep", noop_sleep)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/minimax-m3", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()

    with harness.capture_gateway_responses(capture_path):
        result = asyncio.run(LLM._atransport_call(client, messages=[{"role": "user", "content": "hi"}]))

    assert result == "async-ok"
    assert len(calls) == 2


def test_gateway_response_capture_dumps_full_request_on_error(monkeypatch, tmp_path):
    # A failure's bounded summary record is not enough to diagnose gateway-side
    # rejections (e.g. malformed history). Every error must also persist the exact,
    # uncapped message array that was sent, so the next occurrence is debuggable
    # without a fresh repro against the live gateway.
    from openhands.sdk import LLM

    def original_sync(self, *, messages, **kwargs):
        raise RuntimeError("invalid_body")

    monkeypatch.setattr(LLM, "_transport_call", original_sync)
    capture_path = tmp_path / "gateway_responses.jsonl"
    harness.install_gateway_fix("https://gateway-central.ai.private.hackerrank.link/v1")
    client = type("Client", (), {"model": "openai/qwen-3.8", "base_url": "https://gateway-central.ai.private.hackerrank.link/v1"})()
    messages = [
        {"role": "user", "content": "hello api_key=should-not-appear"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}],
        },
    ]

    with harness.capture_gateway_responses(capture_path):
        with pytest.raises(RuntimeError, match="invalid_body"):
            LLM._transport_call(client, messages=messages)

    record = json.loads(capture_path.read_text(encoding="utf-8"))
    dump_path = Path(record["request_dump_path"])
    assert dump_path.exists()
    assert dump_path.parent == capture_path.parent / "gateway_responses_failures"

    dumped = json.loads(dump_path.read_text(encoding="utf-8"))
    assert dumped["messages"] == messages
    assert dumped["request_validation"]["orphaned_tool_call_count"] == 0
    assert "should-not-appear" in dumped["messages"][0]["content"]  # ordinary content is preserved, not redacted


def test_configuration_loads_safely_and_preserves_shell_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRA_GATEWAY_BASE_URL", "https://astra.example/v1")
    monkeypatch.setenv("LLM_BASE_URL", "https://fallback.example/v1")
    monkeypatch.setenv("ASTRA_GATEWAY_API_KEY", "shell-secret-value")
    monkeypatch.setenv("LLM_API_KEY", "fallback-secret-value")
    assert harness.gateway_url() == "https://astra.example/v1"
    assert harness.api_key() == "shell-secret-value"

    calls = []
    monkeypatch.setattr(harness, "load_dotenv", lambda **kwargs: calls.append(kwargs))
    result = harness.run(
        tmp_path / "missing-workspace",
        tmp_path / "missing-instruction.md",
        "gpt-5.6-luna",
        "low",
        tmp_path / "output",
        env_file=tmp_path / "private.env",
    )
    assert result.status == "failed"
    assert (tmp_path / "output" / "gateway_responses.jsonl").read_text(encoding="utf-8") == ""
    assert calls == [{"dotenv_path": tmp_path / "private.env", "override": False}]

    monkeypatch.delenv("ASTRA_GATEWAY_API_KEY")
    monkeypatch.delenv("LLM_API_KEY")
    with pytest.raises(ValueError, match="required"):
        harness.api_key()
    harness.install_gateway_fix("http://gateway-central.ai.private.hackerrank.link/v1")
    with pytest.raises(ValueError, match="credentials"):
        harness.install_gateway_fix("https://user:pass@gateway-central.ai.private.hackerrank.link/v1")


def test_reasoning_options_are_passed_through(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instruction_file = tmp_path / "instruction.md"
    instruction_file.write_text("stop", encoding="utf-8")
    captured = {}

    class FakeLLM:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.metrics = None

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

    class FakeConversation:
        def __init__(self, **kwargs):
            pass

        def send_message(self, instruction):
            pass

        def run(self):
            pass

    class FakeTool:
        def __init__(self, **kwargs):
            pass

    class FakeCondenser:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setenv("ASTRA_GATEWAY_API_KEY", "valid-gateway-key")
    monkeypatch.setattr(harness, "install_gateway_fix", lambda base_url: None)
    monkeypatch.setitem(sys.modules, "openhands.sdk", SimpleNamespace(
        Agent=FakeAgent,
        Conversation=FakeConversation,
        Event=object,
        LLM=FakeLLM,
    ))
    monkeypatch.setitem(sys.modules, "openhands.sdk.tool", SimpleNamespace(Tool=FakeTool))
    monkeypatch.setitem(sys.modules, "openhands.sdk.context.condenser", SimpleNamespace(LLMSummarizingCondenser=FakeCondenser))
    monkeypatch.setitem(sys.modules, "openhands.tools.file_editor", SimpleNamespace(FileEditorTool=type("FileEditorTool", (), {"name": "file_editor"})))
    monkeypatch.setitem(sys.modules, "openhands.tools.terminal", SimpleNamespace(TerminalTool=type("TerminalTool", (), {"name": "terminal"})))

    for requested in ("xhigh", "ultra", "max"):
        captured.clear()
        result = harness.run(workspace, instruction_file, "test-model", requested, tmp_path / requested)
        assert result.status == "completed"
        assert captured["reasoning_effort"] == requested


def test_gateway_model_max_input_tokens_only_covers_confirmed_models():
    from hackerrank_openhands.harness import gateway_model_max_input_tokens

    # Claude Opus 5.5 has a documented 1.05M-token context window. The harness
    # deliberately uses a lower 524,288-token working cap for reliable agents.
    assert gateway_model_max_input_tokens("claude-opus-5-5") == 524288
    assert gateway_model_max_input_tokens("openai/claude-opus-5-5") == 524288
    assert gateway_model_max_input_tokens("anthropic/claude-opus-5-5") == 524288
    # GPT-6 Astra has a documented 1.05M-token context window and uses the
    # same deliberate 524,288-token working cap.
    assert gateway_model_max_input_tokens("gpt-6-astra") == 524288
    assert gateway_model_max_input_tokens("openai/gpt-6-astra") == 524288

    # 524_288 is minimax-m3's confirmed upstream context window; the returned cap is
    # a safety margin below it, not the raw number, and must not depend on prefix form.
    assert gateway_model_max_input_tokens("minimax-m3") == 419430
    assert gateway_model_max_input_tokens("openai/minimax-m3") == 419430
    # A model with no confirmed window still gets a bound: the conservative default,
    # not a fabricated per-model number and not an unbounded None.
    assert gateway_model_max_input_tokens("gemini-3.7-flash") == 120_000


def test_run_gives_confirmed_models_a_context_window_and_every_agent_a_condenser(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instruction_file = tmp_path / "instruction.md"
    instruction_file.write_text("stop", encoding="utf-8")
    captured_llm_kwargs = {}
    captured_agent_kwargs = {}
    captured_condenser_kwargs = {}
    instances = {}

    class FakeLLM:
        def __init__(self, **kwargs):
            captured_llm_kwargs.update(kwargs)
            self.metrics = None
            instances["llm"] = self

    class FakeCondenser:
        def __init__(self, **kwargs):
            instances["condenser_llm"] = kwargs.get("llm")
            captured_condenser_kwargs.update(kwargs)

    class FakeAgent:
        def __init__(self, **kwargs):
            captured_agent_kwargs.update(kwargs)

    class FakeConversation:
        def __init__(self, **kwargs):
            pass

        def send_message(self, instruction):
            pass

        def run(self):
            pass

    class FakeTool:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setenv("ASTRA_GATEWAY_API_KEY", "valid-gateway-key")
    monkeypatch.setattr(harness, "install_gateway_fix", lambda base_url: None)
    monkeypatch.setitem(sys.modules, "openhands.sdk", SimpleNamespace(Agent=FakeAgent, Conversation=FakeConversation, Event=object, LLM=FakeLLM))
    monkeypatch.setitem(sys.modules, "openhands.sdk.tool", SimpleNamespace(Tool=FakeTool))
    monkeypatch.setitem(sys.modules, "openhands.sdk.context.condenser", SimpleNamespace(LLMSummarizingCondenser=FakeCondenser))
    monkeypatch.setitem(sys.modules, "openhands.tools.file_editor", SimpleNamespace(FileEditorTool=type("FileEditorTool", (), {"name": "file_editor"})))
    monkeypatch.setitem(sys.modules, "openhands.tools.terminal", SimpleNamespace(TerminalTool=type("TerminalTool", (), {"name": "terminal"})))

    result = harness.run(workspace, instruction_file, "minimax-m3", "medium", tmp_path / "minimax")
    assert result.status == "completed"
    assert captured_llm_kwargs["max_input_tokens"] == 419430
    # 300s (the SDK default) has been observed cutting off large-context turns on
    # slower models before they finish responding; 1200s gives them room to complete.
    assert captured_llm_kwargs["timeout"] == 1200
    # Keep a modest retry budget for transient provider disconnects while avoiding
    # the SDK's default of five long-running retries.
    assert captured_llm_kwargs["num_retries"] == 3
    assert captured_llm_kwargs["stream"] is False
    assert captured_llm_kwargs["force_string_serializer"] is True
    # Forces every model's history to condense on a predictable cadence, not only
    # once it approaches whatever that specific model's real token limit is.
    assert captured_llm_kwargs["max_output_tokens"] == 32_768
    assert captured_condenser_kwargs["keep_first"] == 25
    assert captured_condenser_kwargs["max_size"] == 120
    # The condenser must summarize with the same LLM the agent uses, not a fresh one.
    assert instances["condenser_llm"] is instances["llm"]
    assert "condenser" in captured_agent_kwargs

    captured_llm_kwargs.clear()
    captured_agent_kwargs.clear()
    result = harness.run(workspace, instruction_file, "an-unconfirmed-model", "medium", tmp_path / "unconfirmed")
    assert result.status == "completed"
    # Unconfirmed models still get bounded by the conservative default, not left unbounded.
    assert captured_llm_kwargs["max_input_tokens"] == 120_000
    assert "condenser" in captured_agent_kwargs


def test_run_uses_anthropic_output_cap_and_allows_override(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instruction_file = tmp_path / "instruction.md"
    instruction_file.write_text("stop", encoding="utf-8")
    captured = {}

    class FakeLLM:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.metrics = None

    class FakeCondenser:
        def __init__(self, **kwargs):
            pass

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

    class FakeConversation:
        def __init__(self, **kwargs):
            pass

        def send_message(self, instruction):
            pass

        def run(self):
            pass

    class FakeTool:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setenv("ASTRA_GATEWAY_API_KEY", "valid-gateway-key")
    monkeypatch.setattr(harness, "install_gateway_fix", lambda base_url: None)
    monkeypatch.setitem(sys.modules, "openhands.sdk", SimpleNamespace(Agent=FakeAgent, Conversation=FakeConversation, Event=object, LLM=FakeLLM))
    monkeypatch.setitem(sys.modules, "openhands.sdk.tool", SimpleNamespace(Tool=FakeTool))
    monkeypatch.setitem(sys.modules, "openhands.sdk.context", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "openhands.sdk.context.condenser", SimpleNamespace(LLMSummarizingCondenser=FakeCondenser))
    monkeypatch.setitem(sys.modules, "openhands.sdk.context.agent_context", SimpleNamespace(AgentContext=lambda **kwargs: None))
    monkeypatch.setitem(sys.modules, "openhands.tools.file_editor", SimpleNamespace(FileEditorTool=type("FileEditorTool", (), {"name": "file_editor"})))
    monkeypatch.setitem(sys.modules, "openhands.tools.terminal", SimpleNamespace(TerminalTool=type("TerminalTool", (), {"name": "terminal"})))

    result = harness.run(workspace, instruction_file, "openai/claude-opus-5-5", "high", tmp_path / "opus")
    assert result.status == "completed", result.error
    assert captured["model"] == "anthropic/claude-opus-5-5"
    assert captured["stream"] is True
    assert captured["force_string_serializer"] is False
    assert captured["max_output_tokens"] == 65_536
    assert captured["base_url"] == "https://gateway-central.ai.private.hackerrank.link"
    assert captured["extra_headers"] == {"Authorization": "Bearer valid-gateway-key"}

    captured.clear()
    result = harness.run(
        workspace,
        instruction_file,
        "openai/claude-opus-5-5",
        "high",
        tmp_path / "opus-override",
        prompt_caching=True,
        max_output_tokens=98_304,
    )
    assert result.status == "completed"
    assert captured["max_output_tokens"] == 98_304

    captured.clear()
    result = harness.run(
        workspace,
        instruction_file,
        "openai/claude-opus-5-5",
        "high",
        tmp_path / "opus-no-cache",
        prompt_caching=False,
    )
    assert result.status == "completed"
    assert captured["model"] == "openai/claude-opus-5-5"
    assert captured["stream"] is False
    assert captured["force_string_serializer"] is True
    assert captured["max_output_tokens"] == 32_768


def test_failed_run_writes_sanitized_failure_event_and_telemetry(tmp_path):
    output = tmp_path / "output"
    result = harness.run(
        tmp_path / "missing-workspace",
        tmp_path / "missing-instruction.md",
        "gpt-5.6-luna",
        "medium",
        output,
    )
    assert result.status == "failed"
    assert result.exit_code == 1
    records = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert records[-1]["event_type"] == "run_failed"
    manifest = collect(
        result.events_path,
        output / "telemetry.json",
        model="openai/gpt-5.6-luna",
        reasoning="medium",
        started_at=result.started_at,
        completed_at=result.completed_at,
        status=result.status,
        exit_code=result.exit_code,
        error=result.error,
    )
    assert manifest["run"]["status"] == "failed"
    assert manifest["run"]["error"]["type"] == "ValueError"
    assert (output / "trajectory.json").exists()


def test_telemetry_normalizes_usage_tools_trace_and_outputs(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps({"type": "run_event", "event_type": "run_started"}) + "\n"
        + json.dumps({"type": "openhands_event", "event_type": "ActionEvent", "tool_name": "terminal", "Authorization": "Bearer secret"}) + "\n"
        + json.dumps({"type": "openhands_event", "event_type": "ObservationEvent", "tool_name": "terminal"}) + "\n"
        + json.dumps({"type": "openhands_event", "event_type": "ActionEvent", "tool_name": "file_editor"}) + "\n"
        + "not-json\n"
        + json.dumps({"type": "openhands_metrics", "input_tokens": 10, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 5, "output_tokens": 4, "reasoning_tokens": 3, "cost_usd": 1.25}) + "\n",
        encoding="utf-8",
    )
    manifest = collect(
        events,
        tmp_path / "telemetry.json",
        model="openai/gpt-5.6-luna",
        reasoning="high",
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:00:02Z",
        status="completed",
        exit_code=0,
    )
    assert manifest["usage"] == {
        "source": "openhands",
        "input_tokens": 10,
        "cached_input_tokens": 25,
        "cache_read_tokens": 20,
        "cache_write_tokens": 5,
        "output_tokens": 4,
        "reasoning_tokens": 3,
        "total_tokens": 14,
    }
    assert manifest["cost"] == {
        "gateway": {
            "amount_usd": None,
            "currency": "USD",
            "status": "unavailable",
            "source": "gateway",
            "responses_with_cost": 0,
        },
        "openhands": {
            "amount_usd": 1.25,
            "currency": "USD",
            "status": "reported",
            "source": "openhands",
        },
        "custom_estimation": {
            "amount_usd": 0.000005,
            "currency": "USD",
            "status": "estimated",
            "source": "custom_pricing_table",
            "pricing_version": 1,
            "model": "openai/gpt-5.6-luna",
            "normalized_model": "gpt-5.6-luna",
            "requests": 1,
            "requests_with_usage": 1,
            "requests_missing_usage": 0,
            "usage_source": "openhands_usage",
            "pricing": {
                "input_usd_per_million": 0.2,
                "output_usd_per_million": 1.2,
                "cache_read_usd_per_million": 0.02,
                "cache_write_usd_per_million": 0.25,
                "note": "OpenAI catalog pricing",
            },
        },
    }
    assert manifest["tools"] == {
        "total": 2,
        "successful": 1,
        "failed": 0,
        "cancelled": 0,
        "rejected": 0,
        "unknown": 1,
        "by_tool": {"terminal": 1, "file_editor": 1},
    }
    assert manifest["trace"]["event_count"] == 5
    assert manifest["trace"]["invalid_event_count"] == 1
    assert manifest["timing"]["duration_ms"] == 2000
    rendered = "\n".join(path.read_text() for path in (tmp_path / "telemetry.json", tmp_path / "trajectory.json"))
    assert "Bearer secret" not in rendered
    assert "[REDACTED]" in rendered


def test_serializes_structured_event_outcome_metadata():
    class AgentErrorEvent:
        source = "agent"
        timestamp = "2026-09-10T00:00:00Z"
        id = "event-1"
        tool_name = "terminal"
        tool_call_id = "call-1"
        error = "Tool call cancelled by interrupt."
        classification = SimpleNamespace(
            kind=SimpleNamespace(value="agent_outcome"), retryable=False
        )

        def model_dump(self, mode="python"):
            return {
                "id": self.id,
                "tool_call_id": self.tool_call_id,
                "tool_name": self.tool_name,
                "error": self.error,
                "api_key": "nested-secret",
            }

    record = _event_record(AgentErrorEvent())
    assert record["event_type"] == "AgentErrorEvent"
    assert record["tool_call_id"] == "call-1"
    assert record["error"] == "Tool call cancelled by interrupt."
    assert record["error_kind"] == "agent_outcome"
    assert record["data"]["tool_call_id"] == "call-1"
    assert record["data"]["error"] == "Tool call cancelled by interrupt."
    assert record["data"]["api_key"] == "[REDACTED]"


def test_collects_tool_errors_cancellations_and_rejections_by_call_id(tmp_path):
    records = [
        {"type": "openhands_event", "event_type": "ActionEvent", "event_id": "a1", "tool_call_id": "c1", "tool_name": "terminal"},
        {"type": "openhands_event", "event_type": "ObservationEvent", "action_id": "a1", "tool_call_id": "c1", "tool_name": "terminal", "observation_is_error": False},
        {"type": "openhands_event", "event_type": "ActionEvent", "event_id": "a2", "tool_call_id": "c2", "tool_name": "terminal"},
        {"type": "openhands_event", "event_type": "AgentErrorEvent", "tool_call_id": "c2", "tool_name": "terminal", "error": "command failed"},
        {"type": "openhands_event", "event_type": "ActionEvent", "event_id": "a3", "tool_call_id": "c3", "tool_name": "terminal"},
        {"type": "openhands_event", "event_type": "AgentErrorEvent", "tool_call_id": "c3", "tool_name": "terminal", "error": "Tool call cancelled by interrupt."},
        {"type": "openhands_event", "event_type": "ActionEvent", "event_id": "a4", "tool_call_id": "c4", "tool_name": "terminal"},
        {"type": "openhands_event", "event_type": "UserRejectObservation", "action_id": "a4", "tool_call_id": "c4", "tool_name": "terminal", "rejection_source": "user"},
        {"type": "openhands_event", "event_type": "ActionEvent", "event_id": "a5", "tool_call_id": "c5", "tool_name": "terminal"},
        {"type": "openhands_event", "event_type": "ObservationEvent", "action_id": "a5", "tool_call_id": "c5", "tool_name": "terminal", "observation_is_error": True},
    ]
    events = tmp_path / "events.jsonl"
    events.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    manifest = collect(
        events,
        tmp_path / "telemetry.json",
        model="openai/gemini-3.7-flash",
        reasoning="medium",
        started_at="start",
        completed_at="end",
        status="completed",
        exit_code=0,
    )

    trajectory = json.loads((tmp_path / "trajectory.json").read_text(encoding="utf-8"))
    assert [record["status"] for record in trajectory] == [
        "ok",
        "error",
        "cancelled",
        "rejected",
        "error",
    ]
    assert trajectory[1]["outcome_error"] == "command failed"
    assert trajectory[2]["outcome_error"] == "Tool call cancelled by interrupt."
    assert trajectory[3]["outcome_rejection_source"] == "user"
    assert trajectory[4]["outcome_observation_is_error"] is True
    assert manifest["tools"] == {
        "total": 5,
        "successful": 1,
        "failed": 2,
        "cancelled": 1,
        "rejected": 1,
        "unknown": 0,
        "by_tool": {"terminal": 5},
    }


def test_workspace_metrics_compare_non_git_changes(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "modified.txt").write_text("one\ntwo\n", encoding="utf-8")
    (workspace / "deleted.txt").write_text("remove me\n", encoding="utf-8")
    (workspace / "rename-me.txt").write_text("same content\n", encoding="utf-8")
    before = snapshot_workspace(workspace)

    (workspace / "modified.txt").write_text("one\nthree\nfour\n", encoding="utf-8")
    (workspace / "deleted.txt").unlink()
    (workspace / "rename-me.txt").rename(workspace / "renamed.txt")
    (workspace / "added.txt").write_text("new\nfile\n", encoding="utf-8")
    after = snapshot_workspace(workspace)

    metrics = compare_snapshots(before, after)
    assert metrics["files"] == {"added": 1, "modified": 1, "deleted": 1, "renamed": 1, "total_changed": 4}
    assert metrics["lines"] == {"added": 4, "deleted": 2, "changed": 6}
    assert metrics["renames"] == [{"from": "rename-me.txt", "to": "renamed.txt"}]


def test_run_records_workspace_metrics(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "solution.py").write_text("print('before')\n", encoding="utf-8")
    instruction_file = tmp_path / "instruction.md"
    instruction_file.write_text("stop", encoding="utf-8")
    output = tmp_path / "output"

    class FakeLLM:
        def __init__(self, **kwargs):
            self.metrics = None

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

    class FakeConversation:
        def __init__(self, **kwargs):
            pass

        def send_message(self, instruction):
            pass

        def run(self):
            (workspace / "solution.py").write_text("print('after')\n", encoding="utf-8")
            (workspace / "new.py").write_text("print('new')\n", encoding="utf-8")

    class FakeTool:
        def __init__(self, **kwargs):
            pass

    class FakeCondenser:
        def __init__(self, **kwargs):
            pass

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv("ASTRA_GATEWAY_API_KEY", "valid-gateway-key")
        monkeypatch.setattr(harness, "install_gateway_fix", lambda base_url: None)
        monkeypatch.setitem(sys.modules, "openhands.sdk", SimpleNamespace(Agent=FakeAgent, Conversation=FakeConversation, Event=object, LLM=FakeLLM))
        monkeypatch.setitem(sys.modules, "openhands.sdk.tool", SimpleNamespace(Tool=FakeTool))
        monkeypatch.setitem(sys.modules, "openhands.sdk.context.condenser", SimpleNamespace(LLMSummarizingCondenser=FakeCondenser))
        monkeypatch.setitem(sys.modules, "openhands.tools.file_editor", SimpleNamespace(FileEditorTool=type("FileEditorTool", (), {"name": "file_editor"})))
        monkeypatch.setitem(sys.modules, "openhands.tools.terminal", SimpleNamespace(TerminalTool=type("TerminalTool", (), {"name": "terminal"})))

        result = harness.run(workspace, instruction_file, "test-model", "medium", output)
    finally:
        monkeypatch.undo()

    records = [json.loads(line) for line in result.events_path.read_text(encoding="utf-8").splitlines()]
    workspace_event = next(record for record in records if record.get("type") == "workspace_metrics")
    assert workspace_event["files"]["added"] == 1
    manifest = collect(output / "events.jsonl", output / "telemetry.json", model="openai/test-model", reasoning="medium", started_at=result.started_at, completed_at=result.completed_at, status=result.status, exit_code=result.exit_code)
    assert manifest["workspace"]["lines"]["changed"] == 3


def test_package_metadata_and_cli_help_are_available():
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, "pyproject.toml"), "rb") as stream:
        project = tomllib.load(stream)["project"]
    assert project["name"] == "hackerrank-openhands-gateway"
    assert project["scripts"]["hackerrank-openhands"] == "hackerrank_openhands.cli:main"
    completed = subprocess.run(
        [sys.executable, "-m", "hackerrank_openhands.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "Run OpenHands through the HackerRank API Gateway" in completed.stdout
    assert "--prompt-caching" in completed.stdout
    assert "--no-prompt-caching" in completed.stdout


@pytest.mark.live
def test_live_gateway_smoke_when_explicitly_enabled(tmp_path, monkeypatch):
    if os.getenv("HACKERRANK_LIVE_SMOKE") != "1":
        pytest.skip("set HACKERRANK_LIVE_SMOKE=1 to run the live Gateway smoke test")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Gateway Smoke\n", encoding="utf-8")
    instruction = tmp_path / "instruction.md"
    instruction.write_text("Read README.md and report its first Markdown heading, then stop. Do not modify files.\n", encoding="utf-8")
    output = tmp_path / "run"
    result = harness.run(workspace, instruction, os.getenv("HACKERRANK_LIVE_MODEL", "gpt-5.6-luna"), "low", output)
    manifest = collect(
        result.events_path,
        output / "telemetry.json",
        model=os.getenv("HACKERRANK_LIVE_MODEL", "gpt-5.6-luna"),
        reasoning="low",
        started_at=result.started_at,
        completed_at=result.completed_at,
        status=result.status,
        exit_code=result.exit_code,
        error=result.error,
    )
    assert result.status == "completed", manifest
    assert manifest["run"]["exit_code"] == 0
    assert manifest["trace"]["invalid_event_count"] == 0
