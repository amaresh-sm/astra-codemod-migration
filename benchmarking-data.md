# Benchmarking data

Generated from scored candidate artifacts under benchmarking-candidates/. For each run, the newest score.json by modification time is used. Iteration steps counts ActionEvent records, or Pi turn_start records, when available. Total Files and LOC use final telemetry workspace metrics when available, otherwise the retained candidate snapshot. Deps counts distinct direct dependencies in package.json and Cargo manifests. Est cost comes from the custom pricing table; Reported cost comes from Gateway/OpenHands telemetry. — means the source did not provide the field.

| Run-name (unique Id) | Model Name | Reasoning | score | token | tool calls | Iteration steps | Est cost | Reported cost | Duration | Total Files | Loc | deps | largest file |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| openhands-opus-5-high-dev-20260918 | claude-opus-5 | high | 0.1251 | — | — | — | — | — | — | 194 | 78,367 | 31 | codebase/rust/crates/core/tests/fixtures/picomatch_oracle.json (518.8 KB) |
| openhands-opus-5-high-dev-20260919-r2 | claude-opus-5 | high | 0.1303 | — | — | 594 | — | — | 6h 00m 05s | 1,186 | 532,845 | 31 | .verify/baseline/yarn.lock (160.9 KB) |
| pi-opus-5-high-20260919-r2-native-repair-30pct | claude-opus-5 | high | 0.3678 | — | — | — | — | — | — | 123 | 31,837 | 27 | codebase/bin/jscodeshift-native (786.6 KB) |
| openhands-opus-5-medium-dev-20260917 | claude-opus-5 | medium | 0.2724 | 25,609,196 | 269 | 269 | $401.4170 | — | 1h 29m 37s | 7,412 | 1,792,469 | 25 | codebase/bin/jscodeshift-bin (3.7 MB) |
| openhands-claude-sonnet-5-high-20260916 | claude-sonnet-5 | high | 0.3899 | — | — | — | — | — | 1h 13m 59s | 78 | 16,546 | 22 | codebase/yarn.lock (138.5 KB) |
| openhands-sonnet-5-high-dev-20260918-r2 | claude-sonnet-5 | high | 0.0696 | 26,236,638 | 479 | 479 | $89.1230 | — | 3h 08m 51s | 5,815 | 1,697,774 | 31 | codebase/yarn.lock (160.9 KB) |
| pi-sonnet-5-high-20260919-r1 | claude-sonnet-5 | high | 0.0696 | — | — | — | — | — | — | 72 | 10,652 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-sonnet-5-medium-dev-20260918-r3 | claude-sonnet-5 | medium | 0.0904 | 13,307,051 | 312 | 312 | $42.6693 | — | 57m 26s | 4,738 | 1,155,509 | 29 | codebase/package-lock.json (226.6 KB) |
| openhands-sonnet-5-medium-dev-20260919-r5 | claude-sonnet-5 | medium | 0.1285 | 6,951,534 | 164 | 164 | $22.5711 | — | 34m 18s | 5,238 | 1,662,212 | 30 | codebase/yarn.lock (160.9 KB) |
| openhands-deepseek-v4-pro-high-20260917-r3 | deepseek-v4-pro | high | 0.1050 | 6,331,713 | 121 | 121 | $0.3150 | — | 15m 49s | 10,257 | 2,729,211 | 33 | codebase/package-lock.json (226.6 KB) |
| openhands-deepseek-v4-pro-high-20260917-r7 | deepseek-v4-pro | high | 0.1112 | 8,634,351 | 149 | 149 | $0.4842 | — | 24m 13s | 6,607 | 1,987,507 | 33 | bin/jscodeshift (5.7 MB) |
| openhands-deepseek-v4-pro-high-prod-20260918 | deepseek-v4-pro | high | 0.1129 | 4,022,641 | 159 | 159 | $0.4857 | $1.5997 | 23m 13s | 6,186 | 1,889,642 | 28 | bin/jscodeshift (4.6 MB) |
| openhands-deepseek-v4-pro-medium-20260916-r2 | deepseek-v4-pro | medium | 0.1285 | 4,982,274 | 108 | 108 | $0.2951 | $1.1976 | 16m 14s | 1,563 | 8,673 | 29 | bin/jscodeshift (3.2 MB) |
| openhands-deepseek-v4-pro-medium-20260916-r3 | deepseek-v4-pro | medium | 0.1112 | 6,199,967 | 109 | 109 | $0.5088 | — | 19m 14s | 4,006 | 1,026,736 | 30 | codebase/package-lock.json (226.6 KB) |
| openhands-deepseek-v4-pro-medium-prod-20260918 | deepseek-v4-pro | medium | 0.1147 | 8,800,349 | 474 | 474 | $2.4676 | $7.2106 | 1h 20m 28s | 6,047 | 1,473,925 | 30 | codebase/package-lock.json (226.6 KB) |
| openhands-gemini-3-7-flash-high-prod-20260918-q01 | gemini-3.7-flash | high | 0.1424 | 137,986,764 | 3,056 | 3,056 | $16.8939 | — | 2h 13m 03s | 5,157 | 999,577 | 32 | codebase/yarn.lock (160.9 KB) |
| openhands-gemini-3-7-flash-high-prod-20260918-r3 | gemini-3.7-flash | high | 0.1303 | 23,494,232 | 556 | 556 | $3.1047 | $0.0195 | 35m 46s | 4,788 | 706,180 | 31 | codebase/native.node (3.2 MB) |
| openhands-gemini-3-7-flash-prod-dev-20260918 | gemini-3.7-flash | high | 0.1129 | 43,975,815 | 956 | 956 | $5.5101 | — | 53m 31s | 6,784 | 1,682,676 | 31 | codebase/yarn.lock (160.9 KB) |
| openhands-gemini-3-7-flash-medium-prod-20260918 | gemini-3.7-flash | medium | 0.0280 | — | — | — | — | — | 0m 00s | 1 | 12 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-gemini-3-7-flash-medium-prod-20260918-q03 | gemini-3.7-flash | medium | 0.1251 | 16,961,191 | 427 | 427 | $2.1403 | — | 19m 26s | 4,271 | 1,080,779 | 31 | codebase/yarn.lock (160.9 KB) |
| openhands-gemini-3-7-flash-medium-prod-20260918-r2 | gemini-3.7-flash | medium | 0.1407 | 5,529,026 | 162 | 162 | $0.8050 | — | 15m 44s | 4,645 | 1,586,727 | 31 | codebase/yarn.lock (160.9 KB) |
| openhands-1789573954 | glm-5.2 | high | 0.1528 | 29,308,255 | 275 | 275 | $8.2954 | — | 36m 47s | 4,941 | 1,711,786 | 30 | rust/bin/jscodeshift (4.6 MB) |
| openhands-glm-5-2-high-prod-20260919-r1 | glm-5.2 | high | 0.1268 | 20,793,997 | 733 | 733 | $7.8247 | $7.8247 | 1h 06m 46s | 3,206 | 857,922 | 30 | core (92.2 MB) |
| openhands-glm-5-2-high-prod-20260920-r2 | glm-5.2 | high | 0.1268 | 10,289,541 | 396 | 396 | $3.7612 | $3.7612 | 20m 11s | 1,089 | 350,418 | 27 | codebase/bin/jscodeshift (3.1 MB) |
| openhands-glm-5-2-medium-prod-20260918 | glm-5.2 | medium | 0.1112 | 10,606,894 | 431 | 431 | $4.2313 | $4.2313 | 1h 01m 49s | 1,527 | 222,659 | 27 | jscodeshift (907.1 KB) |
| openhands-glm-5-2-medium-prod-20260918-q02 | glm-5.2 | medium | 0.1112 | 9,251,005 | 393 | 393 | $3.4462 | $3.4462 | 25m 15s | 23,882 | 6,834,373 | 31 | codebase/yarn.lock (160.9 KB) |
| openhands-glm-5-2-medium-prod-20260918-q05 | glm-5.2 | medium | 0.1112 | 17,190,637 | 594 | 594 | $6.6824 | $6.6824 | 1h 20m 28s | 630 | 194,009 | 24 | codebase/bin/jscodeshift-rs (902.1 KB) |
| openhands-luna-high-20260916-r2 | gpt-5.6-luna | high | 0.0835 | 857,666 | 64 | 64 | $1.2090 | $0.0465 | 4m 28s | 22 | 103 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-luna-high-20260916-r4 | gpt-5.6-luna | high | 0.0821 | 4,021,503 | 96 | 96 | $5.3207 | $0.1399 | 10m 27s | 10 | 489 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-luna-high-dev-20260918 | gpt-5.6-luna | high | 0.0835 | 713,438 | 72 | 72 | $1.0382 | $0.0507 | 4m 59s | 624 | 200 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-luna-medium-20260915-r2 | gpt-5.6-luna | medium | 0.0835 | 570,512 | 33 | 33 | $0.7662 | $0.0282 | 2m 05s | 7 | 74 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-luna-medium-20260916 | gpt-5.6-luna | medium | 0.0835 | 490,479 | 30 | 30 | $0.6645 | $0.0237 | 2m 37s | 27 | 114 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-luna-medium-prod-dev-20260918 | gpt-5.6-luna | medium | 0.0835 | 376,594 | 37 | 37 | $0.5138 | $0.0199 | 1m 58s | 622 | 7,576 | 24 | codebase/bin/jscodeshift-rs (537.3 KB) |
| openhands-sol-high-20260916 | gpt-5.6-sol | high | 0.3258 | 9,263,504 | 151 | 151 | $12.1454 | $5.5666 | 24m 13s | 1,820 | 357,009 | 27 | codebase/yarn.lock (140.1 KB) |
| openhands-sol-high-20260916-r2 | gpt-5.6-sol | high | 0.2687 | 4,676,669 | 118 | 118 | $1.2455 | $3.4439 | 22m 12s | 389 | 3,583 | 26 | codebase/yarn.lock (160.9 KB) |
| openhands-sol-high-prod-20260919-r1 | gpt-5.6-sol | high | 0.2670 | 9,245,480 | 319 | 319 | $3.2190 | $9.1462 | 56m 29s | 2,162 | 218,056 | 26 | codebase/native/jscodeshift (975.1 KB) |
| openhands-sol-medium-20260917-r4 | gpt-5.6-sol | medium | 0.2793 | 1,954,547 | 80 | 80 | $0.6403 | $1.7220 | 11m 59s | 760 | 5,909 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-sol-medium-20260917-r6 | gpt-5.6-sol | medium | 0.2397 | 1,437,944 | 47 | 47 | $0.5454 | $1.4418 | 14m 04s | 626 | 3,005 | 24 | codebase/dist/jscodeshift (516.8 KB) |
| openhands-sol-medium-prod-20260918-r3 | gpt-5.6-sol | medium | 0.1112 | 2,157,101 | 88 | 88 | $0.7536 | $2.1006 | 17m 21s | 656 | 879 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-terra-high-20260915-r2 | gpt-5.6-terra | high | 0.0789 | 682,924 | 44 | 44 | $0.9737 | $0.4007 | 7m 07s | 69 | 386 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-terra-high-20260916-r4 | gpt-5.6-terra | high | 0.0835 | 566,867 | 37 | 37 | $0.8133 | $0.3551 | 4m 19s | 22 | 481 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-terra-high-prod-dev-20260918 | gpt-5.6-terra | high | 0.1216 | 1,467,510 | 65 | 65 | $2.1053 | $0.9113 | 8m 43s | 87 | 893 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-terra-medium-20260916-r3 | gpt-5.6-terra | medium | 0.0835 | 455,229 | 26 | 26 | $0.6355 | $0.2727 | 3m 04s | 29 | 1,260 | 24 | codebase/yarn.lock (140.1 KB) |
| openhands-terra-medium-dev-20260918 | gpt-5.6-terra | medium | 0.0668 | 509,363 | 39 | 39 | $0.1811 | $0.2715 | 2m 51s | 615 | 485 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-terra-medium-dev-20260919-r1 | gpt-5.6-terra | medium | 0.0835 | 450,980 | 35 | 35 | $0.1666 | $0.2478 | 6m 53s | 64 | 519 | 24 | codebase/native/jscodeshift-native (324.6 KB) |
| openhands-grok-4-5-high-20260917-r2 | grok-4.5 | high | 0.2774 | — | — | — | — | — | — | 80 | 70,269 | 36 | codebase/bin/jscodeshift-rs (5.6 MB) |
| openhands-grok-4-5-high-prod-20260918 | grok-4.5 | high | 0.2791 | 5,194,153 | 106 | 106 | $3.0139 | $3.0139 | 29m 22s | 10,147 | 2,866,990 | 31 | codebase/bin/jscodeshift-native (6.2 MB) |
| openhands-grok-4-5-high-prod-20260919-r2 | grok-4.5 | high | 0.2791 | 2,994,208 | 71 | 71 | $1.7468 | $1.7468 | 19m 24s | 7,074 | 2,284,689 | 31 | bin/jscodeshift (4.6 MB) |
| openhands-1789798211 | grok-4.5 | medium | 0.2557 | 4,005,214 | 60 | 60 | $1.9205 | $1.9205 | 18m 51s | 5,530 | 1,795,460 | 37 | codebase/native/jscodeshift (5.6 MB) |
| openhands-grok-4-5-medium-20260917 | grok-4.5 | medium | 0.2534 | 3,695,753 | 56 | 56 | $4.1232 | — | 22m 49s | 6,227 | 2,203,218 | 30 | codebase/bin/jscodeshift (4.5 MB) |
| openhands-grok-4-5-medium-prod-20260919 | grok-4.5 | medium | 0.2501 | 2,793,763 | 58 | 58 | $1.5684 | $1.5684 | 14m 35s | 6,117 | 2,216,205 | 36 | codebase/yarn.lock (160.9 KB) |
| openhands-grok-4-6-high-dev-20260918 | grok-4.6 | high | 0.1147 | 17,622,525 | 2,134 | 2,134 | $38.6811 | — | 2h 52m 59s | 113 | 2,739 | 27 | codebase/yarn.lock (160.9 KB) |
| openhands-grok-4-6-high-dev-20260920-r1 | grok-4.6 | high | 0.1112 | 107 | — | 7,197 | — | — | 6h 00m 04s | 689 | 350,969 | 29 | codebase/yarn.lock (160.9 KB) |
| openhands-grok-4-6-medium-20260915 | grok-4.6 | medium | 0.1476 | 10,448,577 | 183 | 183 | $21.5824 | — | 37m 11s | 5,052 | 1,775,202 | 31 | bin/jscodeshift (4.6 MB) |
| openhands-grok-4-6-medium-20260916-r2 | grok-4.6 | medium | 0.1476 | 5,724,573 | 150 | 150 | $12.5528 | — | 52m 31s | 1,985 | 359,624 | 27 | bin/jscodeshift (2.3 MB) |
| openhands-grok-4-6-medium-dev-20260921 | grok-4.6 | medium | 0.0280 | — | — | — | — | — | 0m 00s | 1 | 12 | 24 | codebase/yarn.lock (160.9 KB) |
| openhands-kimi-k3-high-20260916-r3 | kimi-k3 | high | 0.3138 | 22,131,260 | 182 | 182 | $8.5976 | — | 48m 06s | 1,108 | 355,985 | 26 | codebase/rust/vendor/hashbrown/src/map.rs (211.0 KB) |
| openhands-kimi-k3-high-20260916-r4 | kimi-k3 | high | 0.2722 | 17,834,780 | 164 | 164 | $7.1027 | — | 40m 16s | 602 | 6,651 | 23 | yarn.lock (160.9 KB) |
| openhands-kimi-k3-high-20260916-r6 | kimi-k3 | high | 0.2843 | 7,162,170 | 107 | 107 | $3.5443 | — | 35m 50s | 561 | 8,388 | 28 | codebase/bin/jscodeshift (5.4 MB) |
| openhands-kimi-k3-medium-20260916-r3 | kimi-k3 | medium | 0.1476 | 2,668,315 | 71 | 71 | $1.6045 | — | 16m 49s | 3,896 | 1,162,284 | 28 | .cargo/registry/src/index.crates.io-1949cf8c6b5b557f/icu_normalizer-2.3.0/tests/data/NormalizationTest.txt (2.7 MB) |
| openhands-kimi-k3-medium-20260917-r4 | kimi-k3 | medium | 0.2670 | 2,897,124 | 85 | 85 | $1.3766 | — | 12m 50s | 4,421 | 1,126,689 | 28 | codebase/bin/jscodeshift-rs (4.6 MB) |
| openhands-kimi-k3-medium-20260917-r6 | kimi-k3 | medium | 0.3034 | 3,127,433 | 85 | 85 | $1.7634 | — | 13m 37s | 1,676 | 696,037 | 26 | codebase/bin/jscodeshift-rust (3.0 MB) |
| openhands-1789661737 | minimax-m3 | high | 0.1268 | 24,218,671 | 497 | 497 | $3.8362 | $1.9181 | 1h 18m 25s | 4,292 | 1,598,959 | 29 | codebase/yarn.lock (160.9 KB) |
| openhands-minimax-m3-high-prod-20260917 | minimax-m3 | high | 0.1147 | 21,148,214 | 494 | 494 | $3.1724 | $1.5862 | 58m 57s | 1,715 | 350,677 | 27 | codebase/yarn.lock (160.9 KB) |
| openhands-minimax-m3-high-prod-20260919 | minimax-m3 | high | 0.1147 | 7,830,692 | 313 | 313 | $1.3531 | $0.6766 | 36m 31s | 4,064 | 1,030,467 | 36 | codebase/yarn.lock (160.9 KB) |
| openhands-1789798212 | minimax-m3 | medium | 0.1233 | 7,590,153 | 345 | 345 | $1.2778 | $0.6389 | 22m 30s | 1,058 | 360,333 | 17 | bin/jscodeshift (4.9 MB) |
| openhands-minimax-m3-medium-prod-20260919-r4 | minimax-m3 | medium | 0.1129 | 13,781,230 | 581 | 581 | $2.2627 | $1.1313 | 34m 34s | 5,361 | 1,640,850 | 33 | codebase/bin/jscodeshift-core (2.7 MB) |
| openhands-minimax-m3-medium-prod-20260919-r5 | minimax-m3 | medium | 0.1112 | 8,030,336 | 363 | 363 | $1.4584 | $0.7292 | 33m 35s | 2,088 | 457,710 | 31 | codebase/yarn.lock (160.9 KB) |
| openhands-qwen-3-8-high-prod-20260918-q04 | qwen-3.8 | high | 0.0280 | — | — | 1,016 | — | — | 6h 00m 04s | 2,601 | 1,297,202 | 30 | codebase/yarn.lock (160.9 KB) |
| openhands-qwen-3-8-high-prod-20260919-q08 | qwen-3.8 | high | 0.0904 | 2,028 | — | 466 | — | — | 6h 00m 05s | 2,674 | 1,555,081 | 31 | codebase/yarn.lock (160.9 KB) |
| openhands-qwen-3-8-high-prod-20260920-r1 | qwen-3.8 | high | 0.0696 | — | — | 511 | — | — | 6h 00m 05s | 3,980 | 1,735,297 | 24 | codebase/yarn.lock (160.9 KB) |

Rows: 71 scored candidate runs.
