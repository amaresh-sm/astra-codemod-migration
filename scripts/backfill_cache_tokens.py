#!/usr/bin/env python3
"""Create or apply the benchmark cache-token backfill.

The default mode is a dry run. Use --apply only after reviewing the report.
Costs are intentionally not recalculated by this tool.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "benchmarking-runs" / "runs"
MANIFEST = ROOT / "benchmarking-runs" / "manifest.json"
REPORT_JSON = ROOT / "benchmarking-runs" / "cache-backfill-dry-run.json"
REPORT_MD = ROOT / "benchmarking-runs" / "cache-backfill-dry-run.md"
LOWER_RATIO = 0.78
UPPER_RATIO = 0.95


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def model_and_provider(telemetry: dict[str, Any], fallback_model: str) -> tuple[str, str]:
    model_info = telemetry.get("model", {})
    if isinstance(model_info, dict):
        model_id = model_info.get("normalized") or model_info.get("name") or model_info.get("model") or fallback_model
        provider = model_info.get("provider")
    else:
        model_id = model_info or fallback_model
        provider = None
    model_id = str(model_id)
    provider = str(provider or (model_id.split("/", 1)[0] if "/" in model_id else "unknown"))
    return model_id.removeprefix("openai/"), provider


def ratio_samples(manifest: dict[str, Any]) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    samples: dict[str, list[float]] = {}
    provider_samples: dict[str, list[float]] = {}
    for run in manifest["runs"]:
        path = RUNS_ROOT / run["model"] / run["reasoning"] / run["run_name"] / "telemetry" / "openhands-telemetry.json"
        if not path.is_file():
            continue
        telemetry = load(path)
        usage = telemetry.get("usage", {})
        input_tokens = int(usage.get("input_tokens") or 0)
        cache_read = int(usage.get("cache_read_tokens") or 0)
        if input_tokens > 0 and cache_read > 0:
            _, provider = model_and_provider(telemetry, run["model"])
            ratio = cache_read / input_tokens
            samples.setdefault(run["model"], []).append(ratio)
            provider_samples.setdefault(provider, []).append(ratio)
    return samples, provider_samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="apply the reviewed backfill to telemetry and metadata")
    args = parser.parse_args()
    manifest = load(MANIFEST)
    samples, provider_samples = ratio_samples(manifest)
    medians = {model: statistics.median(values) for model, values in samples.items()}
    ratios = {model: min(UPPER_RATIO, max(LOWER_RATIO, median)) for model, median in medians.items()}
    provider_medians = {provider: statistics.median(values) for provider, values in provider_samples.items()}
    provider_ratios = {provider: min(UPPER_RATIO, max(LOWER_RATIO, median)) for provider, median in provider_medians.items()}

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for run in manifest["runs"]:
        directory = RUNS_ROOT / run["model"] / run["reasoning"] / run["run_name"]
        telemetry_path = directory / "telemetry" / "openhands-telemetry.json"
        if not telemetry_path.is_file():
            skipped.append({"run": run["run_name"], "model": run["model"], "reason": "telemetry_missing"})
            continue
        telemetry = load(telemetry_path)
        usage = telemetry.get("usage", {})
        input_tokens = int(usage.get("input_tokens") or 0)
        cached_input = int(usage.get("cached_input_tokens") or 0)
        cache_read = int(usage.get("cache_read_tokens") or 0)
        if input_tokens <= 0:
            skipped.append({"run": run["run_name"], "model": run["model"], "reason": "no_input_tokens"})
        elif cached_input > 0 or cache_read > 0:
            skipped.append({"run": run["run_name"], "model": run["model"], "reason": "cache_already_present"})
        else:
            _, provider = model_and_provider(telemetry, run["model"])
            if run["model"] in ratios:
                ratio = ratios[run["model"]]
                ratio_source = "model-level median"
            elif provider in provider_ratios:
                ratio = provider_ratios[provider]
                ratio_source = f"provider-level median fallback ({provider})"
            else:
                skipped.append({"run": run["run_name"], "model": run["model"], "reason": "no_model_or_provider_ratio"})
                continue
            cached = min(input_tokens, math.floor(input_tokens * ratio))
            candidates.append({
                "task": "migrate-jscodeshift-runner-to-rust",
                "run": run["run_name"],
                "model": run["model"],
                "input": input_tokens,
                "ratio": ratio,
                "observed_median_ratio": medians.get(run["model"]),
                "ratio_source": ratio_source,
                "cached": cached,
            })

    report = {
        "schema_version": 1,
        "mode": "apply" if args.apply else "dry-run",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task": "migrate-jscodeshift-runner-to-rust",
        "ratio_rule": "floor(input_tokens * clamped model-level median cache_read_tokens/input_tokens)",
        "fallback_rule": "provider-level median of observed cache ratios when a model-level median is unavailable",
        "ratio_range": [LOWER_RATIO, UPPER_RATIO],
        "costs_changed": False,
        "candidates": candidates,
        "skipped": skipped,
        "model_ratios": {
            model: {"sample_count": len(samples[model]), "observed_median": medians[model], "applied_ratio": ratios[model]}
            for model in sorted(medians)
        },
        "provider_ratios": {
            provider: {"sample_count": len(provider_samples[provider]), "observed_median": provider_medians[provider], "applied_ratio": provider_ratios[provider]}
            for provider in sorted(provider_medians)
        },
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Cache-token backfill dry run",
        "",
        f"Eligible runs: **{len(candidates)}**; skipped runs: **{len(skipped)}**.",
        "Costs, verification results, and candidate artifacts were not changed.",
        "",
        "| Task | Run | Model | Input tokens | Ratio | Ratio source | Cached tokens |",
        "|---|---|---|---:|---:|---|---:|",
    ]
    lines.extend(f"| {x['task']} | `{x['run']}` | `{x['model']}` | {x['input']} | {x['ratio']:.6f} | {x['ratio_source']} | {x['cached']} |" for x in candidates)
    lines += ["", "## Model ratios", "", "| Model | Samples | Observed median | Applied ratio |", "|---|---:|---:|---:|"]
    lines.extend(f"| `{m}` | {v['sample_count']} | {v['observed_median']:.6f} | {v['applied_ratio']:.6f} |" for m, v in sorted(report["model_ratios"].items()))
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.apply:
        for item in candidates:
            path = RUNS_ROOT / next(r["model"] for r in manifest["runs"] if r["run_name"] == item["run"]) / next(r["reasoning"] for r in manifest["runs"] if r["run_name"] == item["run"]) / item["run"]
            telemetry_path = path / "telemetry" / "openhands-telemetry.json"
            telemetry = load(telemetry_path)
            telemetry.setdefault("usage", {})["cached_input_tokens"] = item["cached"]
            telemetry["usage"]["cache_read_tokens"] = item["cached"]
            telemetry["benchmarking_cache_backfill"] = {"ratio": item["ratio"], "source": REPORT_JSON.name}
            telemetry_path.write_text(json.dumps(telemetry, indent=2) + "\n", encoding="utf-8")
            metadata_path = path / "metadata.json"
            metadata = load(metadata_path)
            metadata["benchmarking_cache_backfill"] = {"input_tokens": item["input"], "cached_tokens": item["cached"], "ratio": item["ratio"], "ratio_source": item["ratio_source"], "source": REPORT_JSON.name}
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"{('applied' if args.apply else 'reported')} {len(candidates)} eligible runs; {len(skipped)} skipped")


if __name__ == "__main__":
    main()
