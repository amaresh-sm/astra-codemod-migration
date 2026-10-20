#!/usr/bin/env python3
"""Recalculate stored benchmark estimates from current telemetry and pricing."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarking-runs" / "manifest.json"
RUNS_ROOT = ROOT / "benchmarking-runs" / "runs"
PRICING_SRC = ROOT / "vendor" / "hackerrank-openhands-gateway" / "src"
sys.path.insert(0, str(PRICING_SRC))

from hackerrank_openhands.pricing import (  # noqa: E402
    estimate_custom_cost,
    normalize_usage,
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    manifest = load(MANIFEST)
    updated = 0
    skipped = 0
    changes: list[dict[str, Any]] = []

    for item in manifest["runs"]:
        directory = RUNS_ROOT / item["model"] / item["reasoning"] / item["run_name"]
        telemetry_path = directory / "telemetry" / "openhands-telemetry.json"
        if not telemetry_path.is_file():
            skipped += 1
            continue

        telemetry = load(telemetry_path)
        usage = telemetry.get("usage") or {}
        if normalize_usage(usage) is None:
            skipped += 1
            continue

        model = (telemetry.get("model") or {}).get("name") or item["model"]
        estimate = estimate_custom_cost(model, openhands_usage=usage)
        previous = ((telemetry.get("cost") or {}).get("custom_estimation") or {}).get("amount_usd")
        telemetry.setdefault("cost", {})["custom_estimation"] = estimate
        telemetry["cost"]["recalculated_from_tokens"] = {
            "source": "scripts/recalculate_benchmark_costs.py",
            "cache_tokens_included": True,
        }
        telemetry_path.write_text(json.dumps(telemetry, indent=2) + "\n", encoding="utf-8")
        updated += 1
        changes.append({
            "run": item["run_name"],
            "model": model,
            "before": previous,
            "after": estimate.get("amount_usd"),
            "cache_read_tokens": usage.get("cache_read_tokens", 0),
        })

    print(json.dumps({"updated": updated, "skipped": skipped, "changes": changes}, indent=2))


if __name__ == "__main__":
    main()
