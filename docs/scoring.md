# Scoring and proof of work

Task scores are published on a normalized scale from `0.0` to `1.0`. Each acceptance criterion
has a tunable positive weight; weights may be `0.10`, `0.125`, `0.20`, or another value that reflects
the importance of that behavior. The weights for one task must sum to exactly `1.0`.

The scorer evaluates each criterion independently:

```text
pass    → add the criterion's weight
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
