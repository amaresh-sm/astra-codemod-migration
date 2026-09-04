# ASTRA-RL reference task package

This branch contains a complete, reproducible reference task and the shared tooling used to
author and evaluate long-horizon software tasks.

The repository separates candidate-visible material from verifier-private material. A profile
branch provides the conventions for a brownfield, greenfield, migration, or frontend task; the
shared schemas and validation rules remain on `main`.

## Profiles

- `brownfield` — extend an existing application without breaking its behavior.
- `greenfield` — build a new application from a public behavior contract.
- `migration` — replace an implementation while preserving compatibility.
- `frontend` — change an existing UI using observable, accessible behavior.

See [docs/greenfield-contracts.md](docs/greenfield-contracts.md) for how to create and freeze
backend and UI contracts for a greenfield task.

For the complete authoring path, from task idea through reference, mutants, proof-of-work, and model
proof, see [docs/task-author-setup.md](docs/task-author-setup.md).

Generation supports Codex directly, Claude Code directly, and an OpenAI-compatible adapter that
can target OpenAI or a Portkey OpenAI-compatible endpoint. These are separate authentication and
routing choices; one credential should not be assumed to work for every provider.

## Task package

```text
tasks/                            # candidate-visible task package for this branch
├── task.toml
├── instruction.md
└── public/
    ├── codebase/       # brownfield/frontend/migration source tree when applicable
    ├── contracts/
    └── assets/

verifier/                         # private; never exported to candidates
├── reference-solution/
├── hidden-tests/
├── mutants/
├── acceptance-criteria.yml
├── scoring.yml
└── proof-of-work/
```

## Validate a package

```bash
python3 scripts/validate_task.py tasks
```

The validator is a dependency-free Python script. It checks metadata, required boundaries, and
accidental private-file exports. The shared candidate-generation runner and verifier container
definitions are provided in this repository; task authors supply the task-specific verifier command.

Before evaluation, run the readiness checks as well:

```bash
python3 readiness_checks/check_package.py
python3 readiness_checks/check_acceptance.py
python3 readiness_checks/check_report_privacy.py
python3 readiness_checks/check_scoring.py
python3 readiness_checks/check_determinism.py
python3 readiness_checks/check_proof_work.py
python3 readiness_checks/check_reference.py
python3 readiness_checks/check_mutants.py
```

Create a delivery archive only after all validation and readiness gates pass:

```bash
npm run package -- --output dist/task-package.tar.gz
```

The Python packager stops before writing an archive if any gate fails. The archive contains the
task, private verifier, reference solution, mutants, proof-of-work, environment, harness, and
authoring documentation. It excludes Git data, caches, local run output, and generated `dist/`
files. This is an authoring/submission archive; candidate generation still receives only the
candidate-facing task instruction and `public/` files. Repository absolute paths in retained text
evidence are normalized to `/workspace` in the archive; the source evidence on disk is unchanged.

The package check keeps evaluator-only material out of `tasks/instruction.md` and `tasks/public/`
and verifies the required private verifier and reference `app-setup/` files.

The shared harness language is Python. Task-specific test commands may still use the language and
tools that best fit the task, such as `pytest`, Playwright, `cargo test`, or a Node test runner.

## Candidate run output

Each generation and evaluation run uses a separate directory:

```text
runs/<task-id>/<candidate-id>/
├── candidate/       # the candidate's modified workspace
├── metadata.json    # provider, model, reasoning, timing, status, and cleanup
├── telemetry.json   # token/tool evidence and solution-size metrics
└── reports/
    ├── hidden.junit.xml
    └── score.json
```

The `candidate/` directory is the solution being evaluated. Run outputs are generated artifacts
and should not be copied into a task package or committed as task source.

`telemetry.json` always records duration plus total and changed source/test file and line counts.
It records token use and tool calls only when the provider or agent event log supplies them; each
field says whether it is provider-reported, parsed from an agent log, or unavailable.
Codex and OpenAI-compatible runs request Codex JSONL events; Claude Code runs use its stream-JSON
mode, so all three supported paths can report structured tool use when their CLI provides it.

Docker environments for the two isolated stages are in [environment/](environment/).

The shared harness checks are in `harness_checks/`. They test the reusable scoring and orchestration
code; task-specific behavioral tests belong in the private `verifier/` area of each task.

Checks that determine whether a task package is ready for evaluation belong in
`readiness_checks/`.
