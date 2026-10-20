# Cache-token backfill dry run

Eligible runs: **21**; skipped runs: **57**.
Costs, verification results, and candidate artifacts were not changed.

| Task | Run | Model | Input tokens | Ratio | Ratio source | Cached tokens |
|---|---|---|---:|---:|---|---:|
| migrate-jscodeshift-runner-to-rust | `opus-5-high-dev-20260919-r2` | `claude-opus-5` | 29281315 | 0.950000 | model-level median | 27817249 |
| migrate-jscodeshift-runner-to-rust | `opus-5-medium-dev-20260917` | `claude-opus-5` | 25321211 | 0.950000 | model-level median | 24055150 |
| migrate-jscodeshift-runner-to-rust | `sonnet-5-high-dev-20260918-r2` | `claude-sonnet-5` | 25368882 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 23876314 |
| migrate-jscodeshift-runner-to-rust | `sonnet-5-medium-dev-20260919-r5` | `claude-sonnet-5` | 6808492 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 6407917 |
| migrate-jscodeshift-runner-to-rust | `sonnet-5-medium-dev-20260918-r3` | `claude-sonnet-5` | 13078038 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 12308597 |
| migrate-jscodeshift-runner-to-rust | `sonnet-5-medium-dev-20260922-r1` | `claude-sonnet-5` | 6808492 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 6407917 |
| migrate-jscodeshift-runner-to-rust | `luna-high-20260916-r2` | `gpt-5.6-luna` | 842017 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 792477 |
| migrate-jscodeshift-runner-to-rust | `luna-high-dev-20260918` | `gpt-5.6-luna` | 696709 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 655718 |
| migrate-jscodeshift-runner-to-rust | `luna-high-20260916-r4` | `gpt-5.6-luna` | 3987923 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 3753295 |
| migrate-jscodeshift-runner-to-rust | `luna-medium-20260915-r2` | `gpt-5.6-luna` | 564446 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 531237 |
| migrate-jscodeshift-runner-to-rust | `luna-medium-20260916` | `gpt-5.6-luna` | 484608 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 456096 |
| migrate-jscodeshift-runner-to-rust | `luna-medium-prod-dev-20260918` | `gpt-5.6-luna` | 371678 | 0.941165 | provider-level median fallback (hackerrank-gateway) | 349810 |
| migrate-jscodeshift-runner-to-rust | `sol-high-20260916` | `gpt-5.6-sol` | 9198813 | 0.950000 | model-level median | 8738872 |
| migrate-jscodeshift-runner-to-rust | `terra-high-prod-dev-20260918` | `gpt-5.6-terra` | 1436553 | 0.938912 | model-level median | 1348797 |
| migrate-jscodeshift-runner-to-rust | `terra-high-20260916-r4` | `gpt-5.6-terra` | 554903 | 0.938912 | model-level median | 521005 |
| migrate-jscodeshift-runner-to-rust | `terra-high-20260915-r2` | `gpt-5.6-terra` | 669203 | 0.938912 | model-level median | 628322 |
| migrate-jscodeshift-runner-to-rust | `terra-medium-20260916-r3` | `gpt-5.6-terra` | 447631 | 0.938912 | model-level median | 420286 |
| migrate-jscodeshift-runner-to-rust | `grok-4-6-high-dev-20260918` | `grok-4.6` | 16763503 | 0.942461 | model-level median | 15798943 |
| migrate-jscodeshift-runner-to-rust | `grok-4-6-high-dev-20260920-r1` | `grok-4.6` | 52512939 | 0.942461 | model-level median | 49491383 |
| migrate-jscodeshift-runner-to-rust | `grok-4-6-medium-20260915` | `grok-4.6` | 10277274 | 0.942461 | model-level median | 9685927 |
| migrate-jscodeshift-runner-to-rust | `grok-4-6-medium-20260916-r2` | `grok-4.6` | 5448661 | 0.942461 | model-level median | 5135149 |

## Model ratios

| Model | Samples | Observed median | Applied ratio |
|---|---:|---:|---:|
| `claude-opus-5` | 2 | 0.971363 | 0.950000 |
| `deepseek-v4-pro` | 6 | 0.956591 | 0.950000 |
| `gemini-3.7-flash` | 6 | 0.801399 | 0.801399 |
| `glm-5.2` | 6 | 0.950221 | 0.950000 |
| `gpt-5.6-sol` | 5 | 0.957662 | 0.950000 |
| `gpt-5.6-terra` | 2 | 0.938912 | 0.938912 |
| `grok-4.5` | 5 | 0.897178 | 0.897178 |
| `grok-4.6` | 1 | 0.942461 | 0.942461 |
| `kimi-k3` | 6 | 0.992580 | 0.950000 |
| `minimax-m3` | 6 | 0.946343 | 0.946343 |
| `qwen-3.8` | 6 | 0.888086 | 0.888086 |
