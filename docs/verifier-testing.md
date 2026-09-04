# Writing reliable verifier tests

The verifier is the evidence that a task works. Test behavior a user can observe, not a particular
implementation. A task is ready only when every acceptance criterion has a clear test owner and
the reference solution passes all score-bearing checks.

## Cover the whole contract

For each acceptance criterion, record its public contract entry, fixture or setup, hidden test,
mapped mutant, and positive scoring weight. Cover contract behavior (inputs, outputs, status codes,
validation, and authentication), functional behavior (workflows, errors, persistence, and
isolation), and relevant non-functional behavior (idempotency, concurrency, restart/retry,
ordering, limits, and dependency recovery).

Do not add a criterion only because it is easy to test. Each check should represent a real product
requirement, and each important requirement should have a test.

## Keep tests deterministic

The same candidate and fixture should produce the same result on every run. Avoid wall-clock
assumptions, unrecorded randomness, sleep-based races, shared mutable state, outside network
services, and assertions on unordered output.

Prefer unique test namespaces, explicit readiness checks, controlled clocks, bounded polling with
clear terminal conditions, and API or semantic UI assertions. A timeout is a failure or blocked
setup condition under the task policy; it must not silently become a pass.

Run the complete verifier at least twice against the reference solution and compare criterion
outcomes. Repeat suites with concurrency, delays, retries, browser timing, or service simulation
more often when needed. Investigate every difference before accepting the task.

## Mutants and negative controls

Each important mutant should model a mistake a capable implementer could make and be caught by its
mapped hidden test. Run the verifier against every mutant and record the criterion that failed. An
unrelated criterion should not fail merely because another capability was mutated.

Use a hollow or minimal implementation as a negative control when useful. It may start and expose
surfaces, but it must not receive credit without the required behavior and persisted state.

## Reporting and weights

Keep raw output and repeat-run evidence in the private proof-of-work directory. Publish one normalized
score from `0.0` to `1.0`; keep criterion weights in `scoring.yml` so their relative importance can
be adjusted. Weights must sum to `1.0`. Report failed, blocked, and fixture-unavailable checks
explicitly. Never treat a blocked or unrun check as a pass.
