# Readiness checks

These checks answer whether a task package is ready to publish. They are separate from
`harness_checks/`, which tests the reusable runner itself, and they read only the task's private
evidence.

Run them from the repository root:

```bash
python3 readiness_checks/check_package.py
python3 readiness_checks/check_acceptance.py
python3 readiness_checks/check_report_privacy.py
python3 readiness_checks/check_scoring.py
python3 readiness_checks/check_determinism.py
python3 readiness_checks/check_proof_work.py
python3 readiness_checks/check_reference.py --proof-dir verifier/proof-of-work
python3 readiness_checks/check_mutants.py --verifier-dir verifier --proof-dir verifier/proof-of-work
```

Use `--json` when another script needs a stable result. Both commands exit with status `0` only
when the check passes.

## Reference score gate

`check_reference.py` examines every directory under `reference-runs/`. Each run must contain a
score report with `score: 1.0`, `hard_pass: true`, and a criteria ledger whose entries all pass.
An empty starter package therefore fails honestly until the task author records reference
evidence.

## Package boundary and layout

`check_package.py` checks the handoff boundary and the private package shape. It scans the
candidate-visible `instruction.md` and `public/` files for evaluator material, host-local paths,
and secret-like values. It also requires the task metadata, public contract files, private verifier
inputs, and the reference application's `app-setup/manifest.json`, `build.sh`, `start.sh`, and
`reset.sh`.

## Acceptance and scoring alignment

`check_acceptance.py` requires the acceptance file's task ID to match `task.toml`. Each criterion
must have a requirement, hidden-test reference, mutant reference, and positive weight. Its IDs and
weights must match `scoring.yml` exactly.

## Persisted report privacy

`check_report_privacy.py` rejects host-local paths in retained candidate and proof-of-work reports.
The harness sanitizes new reports automatically; `scripts/sanitize_reports.py` can clean older
evidence once.

## Scoring validity

`check_scoring.py` loads the same `scoring.yml` format as the scorer and validates non-empty,
unique criterion IDs, positive weights, and a total weight of `1.0`. It also scans recorded proof
reports and rejects any blocked criterion that has a non-zero score or award.

## Reference determinism

`check_determinism.py` requires at least two reference runs. It compares only stable outcomes—the
backend criterion statuses, UI capability statuses, and score-criterion statuses—so run-specific
IDs and timestamps do not affect the comparison. It passes only when every ledger and the normalized
score/hard-pass result match the first run. Authors must run the same reference application and
verifier repeatedly and store each result under `proof-of-work/reference-runs/<run-name>/`.

## Proof-of-work evidence

`check_proof_work.py` verifies that the evidence package is usable: at least two reference runs
are present with successful verification and complete scores, every matrix mutant has its applied
patch, verifier evidence, and a score below `1.0`, and at least two candidate runs record their
provider, model, reasoning setting, generation result, tamper check, verification result, and
normalized score. The check validates the metadata that is available; it does not independently
decide whether a named model is frontier-tier.

## Mutant coverage

`check_mutants.py` discovers every `verifier/mutants/*.patch` file and requires a corresponding
entry in `proof-of-work/mutant-matrix.json` and a completed proof run. A run must contain the
applied patch, verifier status, backend criterion ledger, and a score below `1.0` with
`hard_pass: false`.

Each matrix entry names the criteria that the defect is expected to break. The check compares the
mutant ledger with the passing reference ledger: every expected criterion must regress, and any
other regression must be explicitly listed as a related criterion. Unlisted regressions are
reported as unrelated failures, so a mutant cannot receive credit merely because its overall score
dropped.

The mapping is kept in `mutant-matrix.json` rather than inferred from patch text. This makes the
test-to-mutant relationship reviewable and prevents a patch from silently changing what it is
supposed to exercise.

The unit tests for these checks can be run with:

```bash
python3 -m unittest discover -s readiness_checks -q
```
