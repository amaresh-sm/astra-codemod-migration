"""Generate a presentation-ready HTML report from benchmark artifacts."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_ROOT = REPOSITORY_ROOT / "runs/migrate-jscodeshift-runner-to-rust"

# These are the current benchmark candidates. Historical score artifacts are
# discovered by model key and the newest report is selected.
CANDIDATES = (
    {
        "label": "Claude Sonnet medium r4",
        "candidate_id": "openhands-claude-sonnet-medium-20260905-r4",
        "model_key": "sonnet-medium",
    },
    {
        "label": "GPT-5.6 Sol xhigh",
        "candidate_id": "openhands-sol-xhigh-20260907",
        "model_key": "sol-xhigh",
    },
    {
        "label": "GPT-5.6 Luna high",
        "candidate_id": "openhands-luna-high-20260908",
        "model_key": "luna-high",
    },
    {
        "label": "GPT-5.6 Terra medium",
        "candidate_id": "openhands-terra-medium-20260908",
        "model_key": "terra-medium",
    },
    {
        "label": "Grok 4.6 medium",
        "candidate_id": "openhands-grok-4-6-medium-20260908",
        "model_key": "grok-4-6-medium",
    },
    {
        "label": "Grok 4.5 medium",
        "candidate_id": "openhands-grok-4-5-medium-20260909-r2",
        "model_key": "grok-4-5-medium",
    },
    {
        "label": "DeepSeek v4 Pro medium",
        "candidate_id": "openhands-deepseek-v4-pro-medium-20260909-r2",
        "model_key": "deepseek-v4-pro-medium",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the benchmark HTML report")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "runs/migrate-jscodeshift-runner-to-rust/benchmark.html",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def candidate_path(candidate_id: str) -> Path | None:
    matches = list(CANDIDATE_ROOT.rglob(candidate_id + "/candidate"))
    return matches[0] if matches else None


def latest_score_path(model_key: str) -> Path | None:
    matches = [
        path
        for path in (REPOSITORY_ROOT / "runs").rglob("score.json")
        if model_key in str(path)
    ]
    return max(matches, key=lambda path: path.stat().st_mtime, default=None)


def format_int(value: object) -> str:
    return f"{int(value):,}" if isinstance(value, (int, float)) else "—"


def format_seconds(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    minutes, seconds = divmod(round(value), 60)
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def score_value(score: object) -> str:
    return f"{float(score):.2f}" if isinstance(score, (int, float)) else "Not scored"


def compact_number(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{int(value):,}"


def tool_summary(tool_calls: dict) -> str:
    if not isinstance(tool_calls, dict) or not isinstance(tool_calls.get("total"), (int, float)):
        return "Unavailable"
    by_type = tool_calls.get("by_type", {})
    parts = [f"{tool_calls['total']} total"]
    for name in ("shell", "edit", "read", "write", "other"):
        value = by_type.get(name)
        if isinstance(value, (int, float)) and value:
            parts.append(f"{name}: {value}")
    return " · ".join(parts)


def generation_status(metadata: dict, candidate: Path | None) -> str:
    status = metadata.get("status")
    if status == "completed":
        return "Completed"
    if candidate and candidate.is_dir() and status == "failed":
        return "Artifact saved; runner failed"
    return str(status or "Unknown").capitalize()


def collect_candidate(config: dict) -> dict:
    path = candidate_path(config["candidate_id"])
    metadata = read_json(path.parent / "metadata.json") if path else {}
    telemetry = read_json(path.parent / "telemetry.json") if path else {}
    score_path = latest_score_path(config["model_key"])
    score = read_json(score_path) if score_path else {}
    verification = read_json(score_path.parent.parent / "verification.json") if score_path else {}
    criteria = score.get("criteria", {})
    passed = sum(item.get("status") == "pass" for item in criteria.values()) if isinstance(criteria, dict) else 0
    failed = sum(item.get("status") == "fail" for item in criteria.values()) if isinstance(criteria, dict) else 0
    tokens = telemetry.get("tokens", {})
    tools = telemetry.get("tool_calls", {})
    solution = telemetry.get("solution_size", {})
    trace_path = path.parent / "logs/stdout.log" if path else None
    return {
        **config,
        "path": str(path.relative_to(REPOSITORY_ROOT)) if path else None,
        "metadata": metadata,
        "telemetry": telemetry,
        "score": score,
        "score_path": str(score_path.relative_to(REPOSITORY_ROOT)) if score_path else None,
        "verification": verification,
        "passed": passed,
        "failed": failed,
        "tokens": tokens,
        "tools": tools,
        "solution": solution,
        "trace_available": bool(trace_path and trace_path.is_file()),
        "trajectory_available": False,
    }


def esc(value: object) -> str:
    return html.escape(str(value))


def criteria_details(item: dict) -> str:
    score = item.get("score", {})
    criteria = score.get("criteria", {})
    if not isinstance(criteria, dict):
        return "<p>No criterion report available.</p>"
    rows = []
    for name, result in criteria.items():
        status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
        detail = result.get("detail", "") if isinstance(result, dict) else ""
        rows.append(
            f"<li><span class='status {esc(status)}'>{esc(status)}</span> <b>{esc(name)}</b>"
            f"<span class='criterion-detail'>{esc(detail)}</span></li>"
        )
    return "<ul class='criteria'>" + "".join(rows) + "</ul>"


def candidate_detail(item: dict) -> str:
    score = item["score"].get("score")
    telemetry = item["telemetry"]
    tokens = item["tokens"]
    tools = item["tools"]
    metadata = item["metadata"]
    solution = item["solution"]
    details = (
        "<details><summary>View telemetry, paths, and criterion details</summary>"
        "<div class='detail-grid'>"
        f"<div><b>Provider/model</b><br>{esc(metadata.get('provider', '—'))} / {esc(metadata.get('model', '—'))}</div>"
        f"<div><b>Generation status</b><br>{esc(generation_status(metadata, Path(REPOSITORY_ROOT / item['path']) if item['path'] else None))}</div>"
        f"<div><b>Input tokens</b><br>{format_int(tokens.get('input'))} <small>{esc(tokens.get('source', '—'))}</small></div>"
        f"<div><b>Output tokens</b><br>{format_int(tokens.get('output'))}</div>"
        f"<div><b>Cached input</b><br>{format_int(tokens.get('cached_input'))}</div>"
        f"<div><b>Reasoning tokens</b><br>{format_int(tokens.get('reasoning'))}</div>"
        f"<div><b>Tool calls</b><br>{esc(tool_summary(tools))}</div>"
        f"<div><b>Changed files / lines</b><br>{format_int(solution.get('agent_changed_files'))} / {format_int(solution.get('agent_changed_source_lines'))}</div>"
        f"<div><b>Verification</b><br>{esc(item['verification'].get('status', 'Not run'))} · {format_seconds(item['verification'].get('duration_seconds'))}</div>"
        f"<div><b>Cost</b><br><span class='muted'>Not captured in generation telemetry</span></div>"
        f"<div><b>Event trace</b><br>{'Available in logs/stdout.log' if item['trace_available'] else 'Unavailable'}</div>"
        f"<div><b>Full trajectory JSON</b><br><span class='muted'>Not persisted separately</span></div>"
        "</div>"
        f"<p class='path'><b>Candidate:</b> {esc(item['path'] or '—')}<br><b>Score report:</b> {esc(item['score_path'] or 'Not available')}</p>"
        f"{criteria_details(item)}</details>"
    )
    return (
        f"<details class='candidate-detail'><summary><b>{esc(item['label'])}</b>"
        f"<span class='summary-score'>{esc(score_value(score))}</span></summary>{details}</details>"
    )


def chart_score_bars(items: list[dict]) -> str:
    scored = sorted(
        (item for item in items if isinstance(item["score"].get("score"), (int, float))),
        key=lambda item: item["score"]["score"],
        reverse=True,
    )
    rows = []
    for rank, item in enumerate(scored, start=1):
        score = float(item["score"]["score"])
        rows.append(
            f"<div class='bar-row score-row' role='img' aria-label='{esc(item['label'])}: {score:.2f}'>"
            f"<div class='bar-label'><span class='rank'>#{rank}</span><span class='label-copy'>{esc(item['label'])}</span></div>"
            f"<div class='bar-track'><div class='bar-fill score-fill' style='width:{score * 100:.2f}%'></div></div>"
            f"<div class='bar-value'>{score:.2f}</div></div>"
        )
    for item in items:
        if not isinstance(item["score"].get("score"), (int, float)):
            rows.append(
                f"<div class='bar-row unavailable'><div class='bar-label'>{esc(item['label'])}</div>"
                "<div class='bar-track'><div class='bar-fill'></div></div><div class='bar-value'>Not scored</div></div>"
            )
    return "".join(rows) or "<p class='muted'>No score reports available.</p>"


def chart_tool_bars(items: list[dict]) -> str:
    categories = ("shell", "edit", "read", "write", "other")
    totals = [item["tools"].get("total") for item in items if isinstance(item["tools"].get("total"), (int, float))]
    maximum = max(totals, default=1)
    rows = []
    for item in items:
        total = item["tools"].get("total")
        if not isinstance(total, (int, float)):
            rows.append(f"<div class='bar-row unavailable'><div class='bar-label'>{esc(item['label'])}</div><div class='bar-track'><div class='bar-fill'></div></div><div class='bar-value'>Unavailable</div></div>")
            continue
        segments = []
        for category in categories:
            count = item["tools"].get("by_type", {}).get(category, 0)
            if count:
                segments.append(
                    f"<span class='tool-segment tool-{category}' style='width:{float(count) / total * 100:.2f}%' title='{esc(category)}: {int(count)}'></span>"
                )
        rows.append(
                f"<div class='bar-row'><div class='bar-label'>{esc(item['label'])}</div>"
            f"<div class='bar-track tool-track'><div class='tool-stack' style='width:{float(total) / maximum * 100:.2f}%'>{''.join(segments)}</div></div>"
            f"<div class='bar-value'>{int(total):,}</div></div>"
        )
    return "".join(rows)


def chart_token_bars(items: list[dict]) -> str:
    totals = [item["tokens"].get("total") for item in items if isinstance(item["tokens"].get("total"), (int, float))]
    maximum = max(totals, default=1)
    rows = []
    for item in items:
        total = item["tokens"].get("total")
        if not isinstance(total, (int, float)):
            rows.append(f"<div class='bar-row unavailable'><div class='bar-label'>{esc(item['label'])}</div><div class='bar-track'><div class='bar-fill'></div></div><div class='bar-value'>Unavailable</div></div>")
            continue
        rows.append(
            f"<div class='bar-row'><div class='bar-label'>{esc(item['label'])}</div>"
            f"<div class='bar-track'><div class='bar-fill token-fill' style='width:{float(total) / maximum * 100:.2f}%'></div></div>"
            f"<div class='bar-value'>{int(total):,}</div></div>"
        )
    return "".join(rows)


def render(items: list[dict]) -> str:
    scored = [item for item in items if isinstance(item["score"].get("score"), (int, float))]
    best_item = max(scored, key=lambda item: item["score"]["score"], default=None)
    top = best_item["score"].get("score") if best_item else None
    total_tokens = sum(item["tokens"].get("total") or 0 for item in items)
    best_criteria = best_item["score"].get("criteria", {}) if best_item else {}
    best_passed = best_item["passed"] if best_item else 0
    best_total = len(best_criteria) if isinstance(best_criteria, dict) else 0
    best_label = best_item["label"] if best_item else "Best scored run"
    details = "".join(candidate_detail(item) for item in items)
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>jscodeshift Rust Migration Benchmark</title>
<style>
:root {{ --ink:#1f2023; --muted:#74777d; --line:#e3e5e8; --blue:#2f80ed; --blue-deep:#72757a; --violet:#7655ee; --green:#12805c; --red:#c2414d; --soft:#fafafa; }}
.wrap {{ max-width:1660px; margin:0 auto; padding:50px 72px 76px; }} body {{ margin:0; min-width:320px; background:#fff; color:var(--ink); font:15px/1.5 "Avenir Next",Inter,"SF Pro Text",ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }} .task-header {{ padding-bottom:25px; border-bottom:1px solid var(--line); }} .task-header .eyebrow {{ margin-bottom:8px; color:#7b7e84; font-size:12px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; }} .task-header h1 {{ margin:0 0 9px; font-size:32px; font-weight:650; letter-spacing:-.04em; }} .task-header p {{ max-width:940px; margin:0; color:#6f7278; font-size:17px; }} .task-header p + p {{ margin-top:4px; font-size:15px; }} h2 {{ margin:38px 0 16px; font-size:22px; letter-spacing:-.02em; }} .muted,small {{ color:var(--muted); }}
.scope-section {{ padding:22px 0 4px; }} .scope-section h2 {{ margin:0 0 7px; font-size:20px; }} .scope-section p {{ margin:0 0 14px; color:#74777d; }} .scope-list {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px 12px; margin:0; padding:0; list-style:none; }} .scope-list li {{ padding:8px 11px; color:#596a85; background:#f7f9fc; border:1px solid #e7ebf2; border-radius:6px; font-size:13px; }}
.cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:24px 0 8px; }} .card {{ min-height:112px; padding:17px 20px 15px; background:#fff; border:1px solid #dfe5ee; border-radius:11px; box-shadow:0 5px 14px rgba(51,76,116,.045); }} .card-label {{ display:block; color:#66758f; font-size:14px; line-height:1.3; }} .card b {{ display:block; margin-top:17px; color:#2857d8; font-size:31px; line-height:1; letter-spacing:-.05em; white-space:nowrap; }} .card small {{ display:block; margin-top:10px; color:#66758f; font-size:12px; line-height:1.35; }}
.chart-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:18px; margin-top:58px; }} .chart-panel {{ background:#fff; border:1px solid #e3e5e8; border-radius:5px; padding:21px 20px 20px; }} .chart-panel h3 {{ margin:0 0 15px; font-size:15px; }} .chart-legend {{ color:var(--muted); font-size:12px; margin:-7px 0 18px; }}
.bar-row {{ display:grid; grid-template-columns:205px 1fr 86px; align-items:center; gap:12px; margin:14px 0; }} .bar-label {{ display:flex; align-items:center; min-width:0; gap:8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .label-copy {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .rank {{ display:inline-grid; flex:0 0 26px; place-items:center; height:22px; border-radius:7px; color:#52617b; background:#edf2fb; font-size:11px; font-weight:800; }} .bar-track {{ position:relative; height:13px; background:#edf1f8; border-radius:99px; overflow:hidden; }} .bar-fill {{ position:relative; z-index:1; height:100%; min-width:3px; background:var(--blue-deep); border-radius:99px; }} .score-fill {{ background:#315fe0; }} .token-fill {{ background:#7655ee; }} .bar-value {{ text-align:right; font-variant-numeric:tabular-nums; color:#4e5d77; font-size:13px; font-weight:750; }} .unavailable .bar-value {{ font-style:italic; }} .tool-track {{ height:13px; background:transparent; overflow:visible; }} .tool-stack {{ display:flex; height:13px; min-width:3px; border-radius:99px; overflow:hidden; }} .tool-segment {{ height:100%; }} .tool-shell {{ background:#3b6ef5; }} .tool-edit {{ background:#f2a93b; }} .tool-read {{ background:#22ae83; }} .tool-write {{ background:#8768e8; }} .tool-other {{ background:#9aa8bc; }} .legend-item {{ display:inline-flex; align-items:center; margin:0 13px 5px 0; }} .legend-swatch {{ width:9px; height:9px; border-radius:3px; margin-right:5px; }}
.bar-row {{ display:grid; grid-template-columns:205px 1fr 86px; align-items:center; gap:12px; margin:14px 0; }} .bar-label {{ display:flex; align-items:center; min-width:0; gap:8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .label-copy {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .rank {{ display:inline-grid; flex:0 0 26px; place-items:center; height:22px; border-radius:7px; color:#52617b; background:#edf2fb; font-size:11px; font-weight:800; }} .score-row:first-of-type .rank {{ color:#6045c4; background:#eee9ff; }} .bar-track {{ position:relative; height:13px; background:#edf1f8; border-radius:99px; overflow:hidden; box-shadow:inset 0 1px 2px rgba(40,57,94,.08); }} .bar-grid {{ position:absolute; inset:0; opacity:.9; background:none; }} .bar-fill {{ position:relative; z-index:1; height:100%; min-width:3px; background:var(--blue-deep); border-radius:99px; box-shadow:0 2px 7px rgba(53,103,242,.18); }} .score-fill {{ background:#315fe0; }} .token-fill {{ background:#7655ee; }} .bar-value {{ text-align:right; font-variant-numeric:tabular-nums; color:#4e5d77; font-size:13px; font-weight:750; }} .unavailable .bar-value {{ font-style:italic; }} .tool-track {{ height:13px; background:transparent; overflow:visible; box-shadow:none; }} .tool-stack {{ display:flex; height:13px; min-width:3px; border-radius:99px; overflow:hidden; box-shadow:0 2px 7px rgba(44,58,92,.14); }} .tool-segment {{ height:100%; }} .tool-shell {{ background:#3b6ef5; }} .tool-edit {{ background:#f2a93b; }} .tool-read {{ background:#22ae83; }} .tool-write {{ background:#8768e8; }} .tool-other {{ background:#9aa8bc; }} .legend-item {{ display:inline-flex; align-items:center; margin:0 13px 5px 0; }} .legend-swatch {{ width:9px; height:9px; border-radius:3px; margin-right:5px; }}
.details-panel {{ margin-top:18px; }} .candidate-detail {{ background:#fff; border:1px solid var(--line); border-radius:5px; margin:11px 0; padding:0 19px; }} .candidate-detail[open] {{ border-color:#c9cdd2; }} .candidate-detail summary {{ cursor:pointer; padding:16px 0; color:var(--ink); }} .summary-score {{ float:right; color:var(--blue); font-weight:800; font-variant-numeric:tabular-nums; }} .detail-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:4px 0 18px; }} .detail-grid > div {{ padding:11px 12px; background:var(--soft); border:1px solid var(--line); border-radius:5px; }}
.criteria {{ list-style:none; padding:0; margin:16px 0; font-size:13px; }} .criteria li {{ padding:8px 0; border-bottom:1px solid var(--line); }} .status {{ font-weight:700; text-transform:capitalize; margin-right:6px; }} .status.pass {{ color:var(--green); }} .status.fail {{ color:var(--red); }} .status.blocked {{ color:#9a6700; }} .criterion-detail {{ display:block; color:var(--muted); margin:2px 0 0 64px; }} .path {{ color:var(--muted); word-break:break-word; }}
code {{ padding:2px 5px; border-radius:5px; background:#e5edff; color:#35528f; }}
@media(max-width:1100px) {{ .cards {{ grid-template-columns:repeat(2,1fr); }} .scope-list {{ grid-template-columns:repeat(2,1fr); }} }} @media(max-width:900px) {{ .wrap {{ padding:34px 28px 56px; }} .detail-grid {{ grid-template-columns:repeat(2,1fr); }} .chart-grid {{ grid-template-columns:1fr; }} }} @media(max-width:560px) {{ .wrap {{ padding:25px 16px 44px; }} .cards {{ grid-template-columns:1fr; gap:12px; }} .scope-list {{ grid-template-columns:1fr; }} .card {{ min-height:105px; }} .card b {{ margin-top:17px; font-size:30px; }} .card small {{ margin-top:9px; }} .detail-grid {{ grid-template-columns:1fr; }} .bar-row {{ grid-template-columns:132px 1fr 71px; gap:7px; }} .bar-label {{ font-size:12px; }} .chart-panel {{ padding:17px 14px; }} }}
</style></head><body><main class='wrap'>
<header class='task-header'><div class='eyebrow'>Benchmark report</div><h1>Migrate jscodeshift runner to Rust</h1><p>Evaluate how completely each candidate migrates the jscodeshift runner from JavaScript to Rust while preserving its public behavior, CLI, worker execution, and package boundaries.</p><p><b>Library:</b> <a href='https://github.com/facebook/jscodeshift' target='_blank' rel='noopener noreferrer'>jscodeshift</a> is a JavaScript codemod toolkit built around AST parsing, collections, NodePath traversal, builders, templates, and code printing.</p></header>
<section class='scope-section'><h2>Migration scope</h2><p>The benchmark measures compatibility and implementation depth across the full library surface:</p><ul class='scope-list'><li>CLI and argument parsing</li><li>File and directory discovery</li><li>Ignore rules and extensions</li><li>Stdin input</li><li>Transform execution</li><li>Parallel workers</li><li>Error handling and exit codes</li><li>AST parsing and printing</li><li>Collections and NodePath behavior</li><li>Builders, filters, templates, and plugins</li><li>Package-root exports</li><li>Runtime and lifecycle scripts</li><li>Actual Rust ownership of the implementation</li></ul></section>
<section class='cards'>
<div class='card'><span class='card-label'>Runs shown</span><b>{len(items)}</b><small>{len(scored)} scored</small></div>
<div class='card'><span class='card-label'>Total tokens</span><b>{compact_number(total_tokens)}</b><small>across available telemetry</small></div>
<div class='card'><span class='card-label'>Best score</span><b>{score_value(top)}</b><small>normalized benchmark score</small></div>
<div class='card'><span class='card-label'>Passed scenarios</span><b>{best_passed} / {best_total}</b><small>{esc(best_label)}</small></div>
</section>
<div class='chart-grid'>
<section class='chart-panel'><h3>Verifier score</h3><div class='chart-legend'>Normalized score from 0.00 to 1.00 · native Rust ownership carries the largest weights</div>{chart_score_bars(items)}</section>
<section class='chart-panel'><h3>Tool-call composition</h3><div class='chart-legend'><span class='legend-item'><i class='legend-swatch tool-shell'></i>Shell</span><span class='legend-item'><i class='legend-swatch tool-edit'></i>Edit</span><span class='legend-item'><i class='legend-swatch tool-read'></i>Read</span><span class='legend-item'><i class='legend-swatch tool-write'></i>Write</span><span class='legend-item'><i class='legend-swatch tool-other'></i>Other</span></div>{chart_tool_bars(items)}</section>
<section class='chart-panel'><h3>Total token volume</h3><div class='chart-legend'>Provider-reported tokens; bar lengths are relative to the largest run</div>{chart_token_bars(items)}</section>
</div>
<h2>Candidate details</h2><div class='details-panel'>{details}</div>
<h2 id='definitions'>Metric definitions</h2><p>The verifier score combines externally compatible behavior with native Rust ownership. Tool-call counts come from the agent event log; token values are provider-reported when available.</p>
</main></body></html>"""


def main() -> int:
    args = parse_args()
    items = [collect_candidate(config) for config in CANDIDATES]
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(items), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
