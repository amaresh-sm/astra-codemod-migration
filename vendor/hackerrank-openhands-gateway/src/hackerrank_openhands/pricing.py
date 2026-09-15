"""Load and calculate local, explicitly-labelled cost estimates.

The Gateway and OpenHands costs remain the authoritative fields in telemetry.
This module calculates an independent estimate from the human-editable
``pricing.json`` master list.  Rates may be approximate or unavailable when a
provider does not publish a directly matching price; that uncertainty is
carried in the estimate metadata instead of affecting the authoritative costs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


PRICING_VERSION = 1


@dataclass(frozen=True)
class PriceSpec:
    """USD rates per one million tokens for one Gateway model alias."""

    input_usd_per_million: float | None
    output_usd_per_million: float | None
    cache_read_usd_per_million: float | None = None
    cache_write_usd_per_million: float | None = None
    note: str | None = None
    long_context_threshold_tokens: int | None = None
    long_input_usd_per_million: float | None = None
    long_output_usd_per_million: float | None = None
    long_cache_read_usd_per_million: float | None = None

    def rates_for_input(self, input_tokens: int | float) -> tuple[float, float, float | None, float | None]:
        """Return rates for the request's short- or long-context tier."""
        is_long_context = (
            self.long_context_threshold_tokens is not None
            and input_tokens >= self.long_context_threshold_tokens
            and self.long_input_usd_per_million is not None
            and self.long_output_usd_per_million is not None
        )
        if is_long_context:
            return (
                self.long_input_usd_per_million or 0.0,
                self.long_output_usd_per_million or 0.0,
                self.long_cache_read_usd_per_million,
                self.cache_write_usd_per_million,
            )
        return (
            self.input_usd_per_million or 0.0,
            self.output_usd_per_million or 0.0,
            self.cache_read_usd_per_million,
            self.cache_write_usd_per_million,
        )

    @property
    def configured(self) -> bool:
        """Whether enough rates exist to calculate an estimate."""
        return self.input_usd_per_million is not None and self.output_usd_per_million is not None


def _optional_rate(value: Any, *, model: str, field: str) -> float | None:
    """Validate one nullable JSON pricing value."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    raise ValueError(f"Invalid pricing value for {model}.{field}")


def _load_pricing_table() -> dict[str, PriceSpec]:
    """Load and validate the human-editable pricing master list."""
    pricing_path = Path(__file__).with_name("pricing.json")
    try:
        document = json.loads(pricing_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load pricing master list: {pricing_path}") from exc
    if document.get("schema_version") != 1 or not isinstance(document.get("models"), dict):
        raise ValueError("Pricing master list must have schema_version 1 and a models object")

    table: dict[str, PriceSpec] = {}
    for model, values in document["models"].items():
        if not isinstance(model, str) or not isinstance(values, dict):
            raise ValueError("Pricing master list contains an invalid model entry")
        long_context = values.get("long_context") or {}
        if not isinstance(long_context, dict):
            raise ValueError(f"Invalid long_context entry for {model}")
        threshold = long_context.get("threshold_tokens")
        if threshold is not None and (not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= 0):
            raise ValueError(f"Invalid long_context threshold for {model}")
        table[model] = PriceSpec(
            _optional_rate(values.get("input_usd_per_million"), model=model, field="input_usd_per_million"),
            _optional_rate(values.get("output_usd_per_million"), model=model, field="output_usd_per_million"),
            _optional_rate(values.get("cache_read_usd_per_million"), model=model, field="cache_read_usd_per_million"),
            _optional_rate(values.get("cache_write_usd_per_million"), model=model, field="cache_write_usd_per_million"),
            values.get("note"),
            threshold,
            _optional_rate(long_context.get("input_usd_per_million"), model=model, field="long_context.input_usd_per_million"),
            _optional_rate(long_context.get("output_usd_per_million"), model=model, field="long_context.output_usd_per_million"),
            _optional_rate(long_context.get("cache_read_usd_per_million"), model=model, field="long_context.cache_read_usd_per_million"),
        )
    return table


PRICING_TABLE = _load_pricing_table()

MASTER_MODEL_NAMES = tuple(PRICING_TABLE)


def normalize_model_name(model: Any) -> str:
    """Normalize provider-prefixed model names without rejecting unknown aliases."""
    normalized = str(model or "").strip().lower()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    if normalized.startswith("models/"):
        normalized = normalized.removeprefix("models/")
    return normalized


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _first_number(*values: Any) -> int | float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def normalize_usage(usage: Mapping[str, Any]) -> dict[str, int | float] | None:
    """Normalize common OpenAI/LiteLLM/Gateway token usage shapes."""
    prompt_details = usage.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, Mapping) else {}
    input_details = usage.get("input_tokens_details")
    input_details = input_details if isinstance(input_details, Mapping) else {}
    completion_details = usage.get("completion_tokens_details")
    completion_details = completion_details if isinstance(completion_details, Mapping) else {}
    output_details = usage.get("output_tokens_details")
    output_details = output_details if isinstance(output_details, Mapping) else {}
    input_tokens = _first_number(usage.get("input_tokens"), usage.get("prompt_tokens"))
    output_tokens = _first_number(usage.get("output_tokens"), usage.get("completion_tokens"))
    total_tokens = _number(usage.get("total_tokens"))
    if input_tokens is None and total_tokens is not None and output_tokens is not None:
        input_tokens = total_tokens - output_tokens
    if input_tokens is None or output_tokens is None:
        return None

    input_tokens = max(0, input_tokens)
    output_tokens = max(0, output_tokens)
    cache_read = _first_number(
        usage.get("cache_read_input_tokens"),
        usage.get("cache_read_tokens"),
        usage.get("cached_input_tokens"),
        usage.get("cached_tokens"),
        input_details.get("cached_tokens"),
        prompt_details.get("cached_tokens"),
    ) or 0
    cache_write = _first_number(
        usage.get("cache_creation_input_tokens"),
        usage.get("cache_write_input_tokens"),
        usage.get("cache_write_tokens"),
        usage.get("cache_creation_tokens"),
        input_details.get("cache_write_tokens"),
        input_details.get("cache_creation_input_tokens"),
        prompt_details.get("cache_write_tokens"),
        prompt_details.get("cache_creation_input_tokens"),
    ) or 0
    reasoning = _first_number(
        usage.get("reasoning_tokens"),
        usage.get("reasoning_output_tokens"),
        output_details.get("reasoning_tokens"),
        completion_details.get("reasoning_tokens"),
    ) or 0
    # Prompt/input tokens include cached tokens in the common usage shape.
    # Cap cache components so malformed provider data cannot produce a
    # negative uncached count or an inflated estimate.
    cache_read = min(max(0, cache_read), input_tokens)
    cache_write = min(max(0, cache_write), max(0, input_tokens - cache_read))
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cache_read + cache_write,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": total_tokens if total_tokens is not None else input_tokens + output_tokens,
    }


def estimate_custom_cost(
    model: Any,
    *,
    gateway_usages: Iterable[Mapping[str, Any]] = (),
    openhands_usage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate an independent, clearly-labelled estimate without raising errors.

    Gateway request usage is preferred because it can represent each LLM
    request. OpenHands' aggregate usage is used only when no usable Gateway
    usage is available. This estimate is calculated even when Gateway or
    OpenHands also reports a cost, so all available cost views can be compared.
    An unknown model, missing rates, or missing token data produces an
    unavailable result rather than breaking telemetry collection.
    """
    original_model = str(model or "")
    normalized_model = normalize_model_name(model)
    spec = PRICING_TABLE.get(normalized_model)
    gateway_records = list(gateway_usages)
    result: dict[str, Any] = {
        "amount_usd": None,
        "currency": "USD",
        "status": "unavailable",
        "source": "custom_pricing_table",
        "pricing_version": PRICING_VERSION,
        "model": original_model,
        "normalized_model": normalized_model,
        "requests": len(gateway_records),
        "requests_with_usage": 0,
        "requests_missing_usage": 0,
    }
    if spec is None:
        result["reason"] = "model_not_in_pricing_master_list"
        return result
    if not spec.configured:
        result["reason"] = "pricing_not_configured_for_model"
        result["pricing_note"] = spec.note
        return result

    parsed_usages = [normalize_usage(usage) for usage in gateway_records]
    usable_gateway = [usage for usage in parsed_usages if usage is not None]
    missing_gateway = len(parsed_usages) - len(usable_gateway)
    if usable_gateway:
        usages = usable_gateway
        result["requests_with_usage"] = len(usable_gateway)
        result["requests_missing_usage"] = missing_gateway
        source = "gateway_usage"
    else:
        fallback = normalize_usage(openhands_usage or {})
        if fallback is None:
            result["requests_missing_usage"] = len(gateway_records)
            result["reason"] = "token_usage_unavailable"
            return result
        usages = [fallback]
        result["requests"] = 1
        result["requests_with_usage"] = 1
        result["requests_missing_usage"] = len(gateway_records)
        source = "openhands_usage"

    total = 0.0
    for usage in usages:
        input_rate, output_rate, cache_read_rate, cache_write_rate = spec.rates_for_input(usage["input_tokens"])
        uncached = usage["input_tokens"] - usage["cache_read_tokens"] - usage["cache_write_tokens"]
        total += (
            uncached * input_rate
            + usage["cache_read_tokens"] * (cache_read_rate if cache_read_rate is not None else input_rate)
            + usage["cache_write_tokens"] * (cache_write_rate if cache_write_rate is not None else input_rate)
            + usage["output_tokens"] * output_rate
        ) / 1_000_000

    result["amount_usd"] = round(total, 12)
    result["status"] = "partial" if missing_gateway else "estimated"
    result["usage_source"] = source
    if missing_gateway:
        result["reason"] = "some_gateway_responses_missing_token_usage"
    result["pricing"] = {
        "input_usd_per_million": spec.input_usd_per_million,
        "output_usd_per_million": spec.output_usd_per_million,
        "cache_read_usd_per_million": spec.cache_read_usd_per_million,
        "cache_write_usd_per_million": spec.cache_write_usd_per_million,
        "note": spec.note,
    }
    if spec.long_context_threshold_tokens is not None:
        result["pricing"]["long_context_threshold_tokens"] = spec.long_context_threshold_tokens
        result["pricing"]["long_context"] = {
            "input_usd_per_million": spec.long_input_usd_per_million,
            "output_usd_per_million": spec.long_output_usd_per_million,
            "cache_read_usd_per_million": spec.long_cache_read_usd_per_million,
        }
    return result
