# Cache-token backfill dry run

Eligible runs: **13**; skipped runs: **58**.
Costs, verification results, and candidate artifacts were not changed.

| Task | Run | Model | Input tokens | Ratio | Ratio source | Cached tokens |
|---|---|---|---:|---:|---|---:|
| migrate-jscodeshift-runner-to-rust | `opus-5-medium-dev-20260917` | `claude-opus-5` | 25321211 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 23848677 |
| migrate-jscodeshift-runner-to-rust | `sonnet-5-high-dev-20260918-r2` | `claude-sonnet-5` | 25368882 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 23893576 |
| migrate-jscodeshift-runner-to-rust | `sonnet-5-medium-dev-20260919-r5` | `claude-sonnet-5` | 6808492 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 6412550 |
| migrate-jscodeshift-runner-to-rust | `sonnet-5-medium-dev-20260918-r3` | `claude-sonnet-5` | 13078038 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 12317496 |
| migrate-jscodeshift-runner-to-rust | `luna-high-20260916-r2` | `gpt-5.6-luna` | 842017 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 793050 |
| migrate-jscodeshift-runner-to-rust | `luna-high-dev-20260918` | `gpt-5.6-luna` | 696709 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 656192 |
| migrate-jscodeshift-runner-to-rust | `luna-high-20260916-r4` | `gpt-5.6-luna` | 3987923 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 3756008 |
| migrate-jscodeshift-runner-to-rust | `luna-medium-20260915-r2` | `gpt-5.6-luna` | 564446 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 531621 |
| migrate-jscodeshift-runner-to-rust | `luna-medium-20260916` | `gpt-5.6-luna` | 484608 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 456426 |
| migrate-jscodeshift-runner-to-rust | `luna-medium-prod-dev-20260918` | `gpt-5.6-luna` | 371678 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 350063 |
| migrate-jscodeshift-runner-to-rust | `grok-4-6-high-dev-20260918` | `grok-4.6` | 16763503 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 15788635 |
| migrate-jscodeshift-runner-to-rust | `grok-4-6-medium-20260915` | `grok-4.6` | 10277274 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 9679608 |
| migrate-jscodeshift-runner-to-rust | `grok-4-6-medium-20260916-r2` | `grok-4.6` | 5448661 | 0.941846 | provider-level median fallback (hackerrank-gateway) | 5131798 |

## Model ratios

| Model | Samples | Observed median | Applied ratio |
|---|---:|---:|---:|
| `deepseek-v4-pro` | 6 | 0.956591 | 0.950000 |
| `gemini-3.7-flash` | 5 | 0.798898 | 0.798898 |
| `glm-5.2` | 6 | 0.950221 | 0.950000 |
| `gpt-5.6-sol` | 6 | 0.953831 | 0.950000 |
| `gpt-5.6-terra` | 6 | 0.938912 | 0.938912 |
| `grok-4.5` | 5 | 0.897178 | 0.897178 |
| `kimi-k3` | 6 | 0.992580 | 0.950000 |
| `minimax-m3` | 6 | 0.946343 | 0.946343 |
