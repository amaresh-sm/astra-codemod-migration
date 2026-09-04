# Task author setup guide

Use this guide to take a task from an idea to a package that can be scored with confidence.

## 1. Choose a real problem

Start with a problem that a real user, operator, or engineering team could have. It should require
the candidate to understand the supplied repository or product contracts and make changes across
the parts that genuinely participate in the workflow.

For a brownfield task, use an existing application and preserve its current behavior. For a
greenfield task, define the product behavior and public API/UI contracts before the candidate
builds anything. For a migration task, define the compatibility behavior that must survive the
replacement. For a frontend task, describe the user workflow and observable UI behavior.

Keep the candidate instruction focused on the outcome, rules, and constraints. Do not give away the
solution design, private test names, mutant details, database shortcuts, or a step-by-step
implementation recipe. The candidate should be able to discover the right design from the public
code, contracts, and normal product behavior.

## 2. Write the candidate package

Start from the matching profile branch. Put only candidate-visible material in
`public/`: application code for brownfield or frontend tasks, contracts, public assets, and setup
notes. Keep test fixtures in the private verifier package.

For greenfield tasks, use the fixed contract filenames `openapi.contract.json` and
`ui.contract.json` when those surfaces exist. See [Contracts for greenfield tasks](greenfield-contracts.md).

The completed application also supplies `app-setup/manifest.json`. Use the manifest in the
reference task at
`verifier/reference-solution/app-setup/manifest.json`
as the format reference, then set the build, start, reset, readiness URL, public URLs, and actual
datastore list for the task. This is the lifecycle handoff used by the verifier;
it is not part of the candidate-facing `public/` package.

## 3. Define acceptance criteria

List the complete behavior that matters, not only the happy path. Consider inputs, outputs,
validation, authorization, persistence, errors, retries, duplicate requests, concurrency, ordering,
restart behavior, dependency failures, tenant or user isolation, and UI state where relevant.

Each criterion must be independently observable and must represent a real product requirement. Map
it to:

- the public contract or requirement;
- the fixture or setup it needs;
- one hidden test that owns the check;
- a plausible mutant that should fail the check;
- a positive scoring weight.

Keep the weights tunable in `scoring.yml`, and make them add up to exactly `1.0`.

## 4. Build and verify the reference solution

Implement the complete intended behavior in `verifier/reference-solution/`. Run every hidden test
against it. The reference, or golden, solution is the calibration target: it must pass every
score-bearing criterion and receive a normalized score of `1.0`.

If the reference cannot pass a criterion, fix the reference or the criterion before continuing.
Do not lower the criterion simply to make the reference pass.

## 5. Add realistic mutants

A mutant is a deliberately faulty version of the implementation. It should represent a mistake a
capable candidate could realistically make, such as missing validation, incomplete cleanup, lost
retry state, a stale UI update, or a broken compatibility path.

Run the verifier against each mutant and confirm that the intended criterion fails while unrelated
criteria remain meaningful. A mutant that no hidden test catches is evidence of a missing test or
an unclear requirement.

## 6. Calibrate the verifier

Run the reference repeatedly and compare criterion outcomes to detect flaky tests. Run the complete
mutant set and record the result for each one. Check that required fixtures actually contain the
data they claim to exercise, and that blocked or unavailable setup never becomes a pass.

Keep this evidence under the private `proof-of-work/` directory. Include repeat-run results, fixture
checks, mutant results, score stability, and the final matrix.

## 7. Prove task difficulty

Before submitting the task for review, run it with at least two independent frontier models using
each provider's highest supported reasoning setting. Record the provider, model, reasoning setting,
elapsed time, solution file/line counts, normalized score, hard-pass status, and failure categories.
Also retain token and tool-call telemetry when the selected provider exposes it. Every unavailable
metric must be labelled unavailable rather than inferred.

These runs show whether the task requires meaningful repository understanding and sustained work.
They do not replace reference or mutant calibration, and they must not be used to tune the verifier
toward one model. If a provider is unavailable, record that fact rather than simulating a result.

## 8. Final package check

Before submission, confirm that:

- the candidate receives only `instruction.md` and `public/`;
- the verifier, reference solution, hidden tests, mutants, proof-of-work evidence, and scoring rules are private;
- the reference scores `1.0`;
- every acceptance criterion has a test, mutant, fixture decision, and weight;
- repeated reference runs are stable;
- all intended mutants are caught;
- the published output contains one normalized score from `0.0` to `1.0` plus explicit outcomes.

Run the package boundary and layout gate from the repository root:

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

The package gate checks that candidate-visible files contain no evaluator-only material, host-local
paths, or secret-like values, and that the task, public contracts, private verifier, and reference
`app-setup/` handoff are all present. The acceptance gate checks that the criterion IDs and weights
match `scoring.yml`, and that every criterion names a requirement, hidden test, and mutant. The
report-privacy gate rejects persisted evidence with host-local paths. The scoring gate validates
positive weights, the exact `1.0` total, and zero credit for blocked results. The determinism gate
compares stable criterion outcomes across at least two independently stored reference runs. The
proof-of-work gate checks that reference, mutant, and candidate runs have the metadata and reports
needed for review.

Create the delivery archive with the single packaging command:

```bash
npm run package -- --output dist/task-package.tar.gz
```

This runs the task validator and every readiness check first. If any check fails, it exits without
creating or replacing the archive. Git data, caches, local run output, and generated files are
excluded from the archive. Absolute paths in retained text evidence are normalized to
`/workspace` in the archive without changing the local evidence files.
