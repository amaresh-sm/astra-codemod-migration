# HackerRank OpenHands Gateway

Reusable, task-agnostic OpenHands runner for the HackerRank API Gateway.

This is intentionally a thin wrapper. It contains only the agent runtime, Gateway compatibility handling, Gemini request sanitization, and standardized telemetry. It does not contain Docker integration, benchmark logic, candidate management, scoring, or verifiers.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

The package pins the OpenHands SDK and tools to `1.44.1` for reproducible behavior.

## Test

```bash
python -m pip install -e '.[test]'
python -m pytest
```

The live Gateway smoke test is opt-in so normal test runs do not spend API credits:

```bash
HACKERRANK_LIVE_SMOKE=1 python -m pytest -m live
```

## Configure the Gateway

```bash
export ASTRA_GATEWAY_API_KEY="..."
export ASTRA_GATEWAY_BASE_URL="https://gateway-central.ai.private.hackerrank.link/v1"
```

`LLM_API_KEY` and `LLM_BASE_URL` are also accepted for compatibility. The CLI automatically loads `.env` from the current directory. Use `--env-file /path/to/private.env` when the file is elsewhere. Existing shell variables take precedence. Credentials are never written to telemetry.

## Run an agent

```bash
hackerrank-openhands run \
  --workspace ./repository \
  --instruction-file ./instruction.md \
  --model openai/gemini-3.7-flash \
  --reasoning medium \
  --output ./run-output
```

Supported reasoning values are `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `ultra`, and `max`; the default is `medium`. The selected value is passed unchanged to OpenHands and the Gateway. Whether a value is supported is determined by the selected model and Gateway.

The workspace is the general coding workspace visible to OpenHands. Any supporting files can be placed in that workspace; there is no benchmark-specific input format.

Output artifacts retain the captured event and response content by default. Pass `--redact` to replace likely credential fields and bearer values with `[REDACTED]`. Redaction is intentionally opt-in for this internal harness; treat default outputs as sensitive.

The output contains:

```text
run-output/
├── events.jsonl
├── gateway_responses.jsonl
├── trajectory.json
└── telemetry.json
```

## Telemetry

Telemetry records model and reasoning configuration, run and per-LLM-request timing, input/output/cache/reasoning/total tokens, separate Gateway-reported and OpenHands-calculated costs, tool counts, trajectory metadata, failure details, event counts, and an event integrity hash. Gateway costs are summed from response `usage.cost` fields when available; OpenHands costs come from its accumulated metrics. Tool outcomes are correlated using OpenHands action and tool-call IDs. The trajectory distinguishes `ok`, `error`, `cancelled`, `rejected`, and `unknown` outcomes, including OpenHands observation error flags and agent error metadata. Missing provider data is represented as unavailable rather than silently converted to zero.

The wrapper records each OpenHands event's JSON-serializable payload under `data`, along with convenient event IDs, tool names, tool-call IDs, action IDs, error classifications, retryability, cancellation messages, and rejection sources. This makes the event stream reusable for downstream analysis without requiring another OpenHands callback.

Workspace metrics compare snapshots taken before and after the run, so they work without Git. They report added, modified, deleted, and exact-content renamed files, plus added, deleted, and changed text lines. The output directory and common dependency/build directories are excluded.

Event payloads are captured as emitted by OpenHands. When `--redact` is enabled, credential-bearing fields and bearer values are redacted; event content such as prompts and tool output may still be retained because it is part of the OpenHands event payload.

`gateway_responses.jsonl` contains the bounded response returned by the Gateway for each LLM transport call, including provider-specific usage, cost, and `latency_ms` fields when available. `telemetry.json` summarizes those request latencies under `timing.llm_requests`. With `--redact`, likely credentials and bearer values are sanitized. Capture is observational: the response is returned to OpenHands unchanged, and capture failures do not fail the run. Responses larger than the capture limit are recorded as metadata with `response_truncated: true`. Gateway response bodies can contain task prompts and model output, so protect this file accordingly.

## Gemini compatibility

For Gemini models, the Gateway adapter removes `prompt_cache_key` from both top-level and nested `extra_body` request fields. Other models are left unchanged. The adapter also removes optional message fields rejected by the Gateway portable route.

## Supporting files

Put any files the agent may need in the workspace. The wrapper does not require a separate context-file format:

```text
repository/
├── src/
├── tests/
├── docs/
└── API_SPEC.md
```

## Current status

This is version `0.1.0`. Local compatibility and telemetry checks pass. Live OpenHands/Gateway smoke tests were verified with the pinned dependencies and Gateway credentials; future runs require the same credentials to be available in the execution environment.
