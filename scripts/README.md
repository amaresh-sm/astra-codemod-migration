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

Candidate generation supports three adapters through one command:

```bash
python3 -m astra_harness.generate \
  --task tasks \
  --provider <codex|openai-compatible|claude-code> \
  --model <model-name> \
  --reasoning <low|medium|high|xhigh|max> \
  --env-file /absolute/path/to/private-provider.env
```

The adapter selects the provider's native CLI flags. The container receives only `instruction.md`
and `public/`; credentials are injected from the private env file at runtime. Use `--command` when
a site-specific CLI installation has a different invocation syntax.

For `claude-code`, provide `ANTHROPIC_API_KEY` in the private env file. A Claude Code login can
also be copied explicitly with `--claude-credentials-file /absolute/path/to/.credentials.json`.
The API key is preferred for long-running isolated generations because copied OAuth credentials may
expire.

`openai-compatible` uses the Codex agent with `OPENAI_API_KEY` and `OPENAI_BASE_URL`. Set the base
URL to the OpenAI API for OpenAI models or to a Portkey OpenAI-compatible endpoint for a routed
model. A Portkey key is not an OpenAI key; the env file must match the endpoint being used.

## Verification and scoring

Run the task's private verifier against a generated candidate:

```bash
python3 -m astra_harness.verify \
  --task tasks \
  --candidate runs/<task-id>/<candidate-id>/candidate \
  --run runs/<task-id>/<candidate-id> \
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
  --run runs/<task-id>/<candidate-id>
```

The scorer reads private `verifier/scoring.yml`, validates that weights total `1.0`, and writes
`reports/score.json`. The published score is normalized to `0.0–1.0`; missing criteria are blocked
and never silently treated as passes.
