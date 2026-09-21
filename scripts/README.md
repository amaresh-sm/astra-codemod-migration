# Shared harness scripts

The shared harness uses Python for orchestration, isolation, telemetry, proof-of-work, scoring, and
package validation. Task-specific tests are invoked by the Python harness and may use their native
toolchain, such as `pytest`, Playwright, `cargo test`, or a Node test runner.

Create the authoring package after the readiness gates pass:

```bash
npm run package -- --output dist/task-package.tar.gz
```

The command is implemented by `scripts/package_task.py`. It runs every validator and readiness
check before creating a deterministic archive; a failed check prevents archive creation.

Candidate generation supports four adapters through one command:

```bash
python3 -m astra_harness.generate \
  --task tasks \
  --provider <codex|openai-compatible|claude-code|openhands> \
  --model <model-name> \
  --reasoning <low|medium|high|xhigh|max> \
  [--openhands-env-file /absolute/path/to/private-openhands.env]
```

Generated candidates and their run artifacts are stored under
`benchmarking-candidates/<run-id>/` by default. Use `--runs-root` only when a different artifact
root is intentional. The task ID is retained in `metadata.json`; it is not duplicated in the path.

To queue multiple OpenHands runs without exceeding the global live-container limit, use the
ordered queue in `config/candidate-generation-queue.json`:

```bash
npm run schedule:generate -- --task tasks
```

The scheduler counts live Docker generation containers for this task, so stale `metadata.json`
files do not consume slots. It leaves already-running jobs alone, persists state in the ignored
`benchmarking-candidates/.generation-scheduler-state.json`, and starts the next queued job only
when the live count is below `max_concurrency` (currently 4). Queue jobs use the `.dev.env` or
`.prod.env` file selected by each job and the same 6-hour/3-GB generation settings as the direct
OpenHands command. Every 15 minutes it checks for 20-minute inactivity, snapshots the available
candidate and container log, records whether lifecycle files were present, and removes only the
stale container. Use `--once` for a single scheduling pass.

The adapter selects the provider's native CLI flags. The container receives only `instruction.md`
and `public/`; credentials are injected at runtime. OpenHands reads the private `.env` from
`../hackerrank-openhands-gateway/.env` by default; `--openhands-env-file` overrides that location.
Only `ASTRA_GATEWAY_API_KEY`, `ASTRA_GATEWAY_BASE_URL`, `LLM_API_KEY`, and `LLM_BASE_URL` are
accepted, and the filtered values are streamed into the container's `/tmp` tmpfs. Use `--command`
when a site-specific CLI installation has a different invocation syntax.

For `claude-code`, provide `ANTHROPIC_API_KEY` in the private env file. A Claude Code login can
also be copied explicitly with `--claude-credentials-file /absolute/path/to/.credentials.json`.
The API key is preferred for long-running isolated generations because copied OAuth credentials may
expire.

`openai-compatible` uses the Codex agent with `OPENAI_API_KEY` and `OPENAI_BASE_URL`. Set the base
URL to the OpenAI API for OpenAI models or to a Portkey OpenAI-compatible endpoint for a routed
model. A Portkey key is not an OpenAI key; the env file must match the endpoint being used.

`openhands` uses the vendored `hackerrank-openhands-gateway` package and routes OpenHands through
the HackerRank Gateway. Its command and telemetry are handled inside the isolated generation image;
the reusable package's `.env` is the single source for Gateway credentials and optional base URL.

## Verification and scoring

Run the task's private verifier against a generated candidate:

```bash
python3 -m astra_harness.verify \
  --task tasks \
  --candidate benchmarking-candidates/<candidate-id>/candidate \
  --run benchmarking-candidates/<candidate-id> \
  --verifier-command '<task-specific test command>'
```

The verifier command runs only inside the private verifier container. Candidate lifecycle commands
are read from the public manifest and run separately in the candidate runtime. The verifier command
must write `/output/criteria.json` with one `pass`, `fail`, or `blocked` status for each criterion.

For the reference Data Consent package, the task-specific command is:

```bash
python3 /input/verifier/run.py \
  --candidate /input/candidate \
  --output /output
```

It runs black-box checks against the already-running candidate, writes component
evidence, and adapts that evidence to the shared `reports/criteria.json` handoff.
Other tasks can provide their own command with the same handoff.

Then calculate the published score:

```bash
python3 -m astra_harness.score \
  --task tasks \
  --run benchmarking-candidates/<candidate-id>
```

The scorer reads private `verifier/scoring.yml`, validates that weights total `1.0`, and writes
`reports/score.json`. The published score is normalized to `0.0–1.0`; missing criteria are blocked
and never silently treated as passes.

For one idempotent command that prepares the runtime/verifier images when missing or stale, runs
the isolated verification, and calculates the score, use:

```bash
npm run benchmark -- \
  --task tasks \
  --candidate benchmarking-candidates/<candidate-id>/candidate \
  --run benchmarking-candidates/<candidate-id>/verification
```

The command records a source digest on each Docker image. Unchanged images are reused; changed or
missing images are rebuilt. A low candidate score is still a successful benchmark result, while
infrastructure or verifier failures return a non-zero exit status.

Generate the presentation report from the stored candidate telemetry and verifier artifacts with:

```bash
npm run report:benchmark
```

This writes `runs/migrate-jscodeshift-runner-to-rust/benchmark.html`.
