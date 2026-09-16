# Scoring and proof of work

Task scores are published on a normalized scale from `0.0` to `1.0`. Each acceptance criterion
has a tunable positive weight; weights may be `0.10`, `0.125`, `0.20`, or another value that reflects
the importance of that behavior. The weights for one task must sum to exactly `1.0`.

Migration tasks assign every criterion to an explicit implementation domain. Compatibility is
still measured for every candidate, but it is not automatically migration credit: public behavior
is credited only in proportion to Rust ownership proved for the same domain.

```text
operational surface          0.04
domain-gated behavior        0.09
validated Rust foundation    0.05
validated migration progress 0.12
proven Rust ownership        0.70
                           ------
                             1.00
```

A thin Rust launcher that delegates to a retained JavaScript engine is capped at `0.0400`, even
when its JavaScript behavior passes many scenarios. The report retains that larger value as
`observed_wrapper_score` for diagnosis. A substantive migration first needs a native public
launcher backed by meaningful first-party Rust implementation work; it then earns its `0.05`
foundation plus up to `0.12` for independently evidenced Rust arguments, file handling, runner,
worker, and package subsystems. This is progress credit, not behavioral ownership. It then earns
any independently proven Rust domains and only the behavior unlocked by those domains. JavaScript
retained for AST/core compatibility cannot block separately traced Rust CLI, file, or worker domains,
but it cannot earn AST/core/package ownership credit either. Reports include `score_components`,
`ownership_domains`, and `migration_status` in addition to the normalized `score`.

The scorer evaluates each criterion independently:

```text
pass    → add the criterion's weight
partial → add the reported fraction of the criterion's weight
fail    → add zero
blocked → apply the task's blocked policy and report it explicitly
```

The published result should include the normalized score, hard-pass status, and criterion outcomes.
Raw scenario counts and diagnostic pass rates may be retained internally, but they must not be
presented as a second competing score.

## Difficulty evidence

After the reference solution and mutants are checked, and before submitting the task package for
review, run the completed task with at least two different frontier models at their maximum
supported reasoning capacity. Preserve the run metadata, normalized score, and failure categories
so reviewers can see whether the task requires meaningful repository understanding and long-horizon
execution. This evidence does not change the task's weights and must not be used to tune the
verifier toward a particular model.

Recommended artifact layout:

```text
proof-of-work/
├── reference-runs/
├── mutant-runs/
├── candidate-runs/
└── summary.json
```
