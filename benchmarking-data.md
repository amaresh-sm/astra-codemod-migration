# Benchmarking data- Codemod Migration

| Run-name (unique Id) | Model Name | Reasoning | score | Token (input/output/reasoning/cache-read) | tool calls | Iteration steps | Est cost | Reported cost | Duration | Total Files | Loc | deps | largest file |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| pi-opus-5-high-20260919-r2-native-repair-30pct | claude-opus-5 | high | 0.3678 | 8.2M/338.5K/279.6K/0 | 98 | 90 | $148.8822 | — | 1h 19m 10s | 123 | 31,837 | 27 | rust/crates/jscodeshift-core/src/glob.rs (679 LOC) |
| openhands-opus-5-high-dev-20260919-r2 | claude-opus-5 | high | 0.1303 | 29.3M/1.5M/1.2M/0 | 594 | 594 | $553.2877 | — | 6h 00m 05s | 1,186 | 532,845 | 31 | crates/jscodeshift-core/src/glob/parse.rs (1,330 LOC) |
| openhands-opus-5-high-dev-20260918 | claude-opus-5 | high | 0.1251 | 22.0M/739.7K/448.2K/0 | 559 | 559 | $384.8871 | — | 3h 01m 45s | 194 | 78,367 | 31 | rust/crates/core/src/picomatch.rs (1,881 LOC) |
| openhands-opus-5-medium-dev-20260917 | claude-opus-5 | medium | 0.2724 | 25.3M/288.0K/154.1K/23.8M | 269 | 269 | $79.4599 | — | 1h 29m 37s | 7,412 | 1,792,469 | 25 | rust/src/glob.rs (1,334 LOC) |
| openhands-claude-sonnet-5-high-20260916 | claude-sonnet-5 | high | 0.3899 | 53.7M/249.0K/128.1K/0 | 320 | 320 | $164.9011 | — | 1h 13m 59s | 78 | 16,546 | 22 | native/src/main.rs (732 LOC) |
| openhands-sonnet-5-high-dev-20260918-r2 | claude-sonnet-5 | high | 0.0696 | 25.4M/867.8K/683.4K/23.9M | 479 | 479 | $24.6103 | — | 3h 08m 51s | 5,815 | 1,697,774 | 31 | src/Collection.js (481 LOC) |
| pi-sonnet-5-high-20260919-r1 | claude-sonnet-5 | high | 0.0696 | 5.1M/69.5K/61.9K/0 | 58 | 52 | $16.4214 | — | 59m 57s | 72 | 10,652 | 24 | src/Collection.js (481 LOC) |
| openhands-sonnet-5-medium-dev-20260919-r5 | claude-sonnet-5 | medium | 0.1285 | 6.8M/143.0K/69.7K/6.4M | 164 | 164 | $5.2572 | — | 34m 18s | 5,238 | 1,662,212 | 30 | rust-cli/src/args.rs (626 LOC) |
| openhands-sonnet-5-medium-dev-20260918-r3 | claude-sonnet-5 | medium | 0.0904 | 13.1M/229.0K/113.3K/12.3M | 312 | 312 | $9.4121 | — | 57m 26s | 4,738 | 1,155,509 | 29 | bridge/Collection.js (481 LOC) |
| openhands-deepseek-v4-pro-high-prod-20260918 | deepseek-v4-pro | high | 0.1129 | 3.9M/78.5K/42.5K/3.6M | 159 | 159 | $0.4857 | $1.5997 | 23m 13s | 6,186 | 1,889,642 | 28 | src/Collection.js (481 LOC) |
| openhands-deepseek-v4-pro-high-20260917-r7 | deepseek-v4-pro | high | 0.1112 | 8.6M/75.2K/35.7K/8.3M | 149 | 149 | $0.4842 | — | 24m 13s | 6,607 | 1,987,507 | 33 | src/Collection.js (481 LOC) |
| openhands-deepseek-v4-pro-high-20260917-r3 | deepseek-v4-pro | high | 0.1050 | 6.3M/51.9K/23.7K/6.2M | 121 | 121 | $0.3150 | — | 15m 49s | 10,257 | 2,729,211 | 33 | src/Collection.js (481 LOC) |
| openhands-deepseek-v4-pro-medium-20260916-r2 | deepseek-v4-pro | medium | 0.1285 | 4.9M/63.7K/37.7K/4.8M | 108 | 108 | $0.2951 | $1.1976 | 16m 14s | 1,563 | 8,673 | 29 | src/Collection.js (481 LOC) |
| openhands-deepseek-v4-pro-medium-prod-20260918 | deepseek-v4-pro | medium | 0.1147 | 8.5M/255.7K/180.9K/5.8M | 474 | 474 | $2.4676 | $7.2106 | 1h 20m 28s | 6,047 | 1,473,925 | 30 | src/runner.rs (606 LOC) |
| openhands-deepseek-v4-pro-medium-20260916-r3 | deepseek-v4-pro | medium | 0.1112 | 6.1M/70.5K/30.3K/5.8M | 109 | 109 | $0.5088 | — | 19m 14s | 4,006 | 1,026,736 | 30 | src/Collection.js (481 LOC) |
| openhands-gemini-3-7-flash-high-prod-20260918-q01 | gemini-3.7-flash | high | 0.1424 | 137.8M/230.9K/0/111.2M | 3,056 | 3,056 | $16.8939 | — | 2h 13m 03s | 5,157 | 999,577 | 32 | src/args_parser.rs (571 LOC) |
| openhands-gemini-3-7-flash-high-prod-20260918-r3 | gemini-3.7-flash | high | 0.1303 | 23.4M/98.7K/0/18.5M | 556 | 556 | $3.1047 | $0.0195 | 35m 46s | 4,788 | 706,180 | 31 | src/Collection.js (481 LOC) |
| openhands-gemini-3-7-flash-prod-dev-20260918 | gemini-3.7-flash | high | 0.1129 | 43.9M/93.3K/0/35.1M | 956 | 956 | $5.5101 | — | 53m 31s | 6,784 | 1,682,676 | 31 | src/Collection.js (481 LOC) |
| openhands-gemini-3-7-flash-medium-prod-20260918-r2 | gemini-3.7-flash | medium | 0.1407 | 5.5M/35.1K/0/4.1M | 162 | 162 | $0.8050 | — | 15m 44s | 4,645 | 1,586,727 | 31 | src/args.rs (790 LOC) |
| openhands-gemini-3-7-flash-medium-prod-20260918-q03 | gemini-3.7-flash | medium | 0.1251 | 16.9M/50.3K/0/13.6M | 427 | 427 | $2.1403 | — | 19m 26s | 4,271 | 1,080,779 | 31 | src/args.rs (658 LOC) |
| openhands-gemini-3-7-flash-medium-prod-20260918 | gemini-3.7-flash | medium | 0.0280 | — | — | — | — | — | 0m 00s | 1 | 12 | 24 | src/Collection.js (481 LOC) |
| openhands-1789573954 | glm-5.2 | high | 0.1528 | 29.2M/108.9K/20.5K/29.0M | 275 | 275 | $8.2954 | — | 36m 47s | 4,941 | 1,711,786 | 30 | src/Collection.js (481 LOC) |
| openhands-glm-5-2-high-prod-20260919-r1 | glm-5.2 | high | 0.1268 | 20.5M/289.2K/64.0K/19.4M | 733 | 733 | $7.8247 | $7.8247 | 1h 06m 46s | 3,206 | 857,922 | 30 | src/Collection.js (481 LOC) |
| openhands-glm-5-2-high-prod-20260920-r2 | glm-5.2 | high | 0.1268 | 10.2M/129.9K/30.2K/9.7M | 396 | 396 | $3.7612 | $3.7612 | 20m 11s | 1,089 | 350,418 | 27 | rust/src/args.rs (657 LOC) |
| openhands-glm-5-2-medium-prod-20260918 | glm-5.2 | medium | 0.1112 | 10.4M/165.8K/72.4K/9.8M | 431 | 431 | $4.2313 | $4.2313 | 1h 01m 49s | 1,527 | 222,659 | 27 | src/Collection.js (481 LOC) |
| openhands-glm-5-2-medium-prod-20260918-q02 | glm-5.2 | medium | 0.1112 | 9.1M/132.6K/50.9K/8.7M | 393 | 393 | $3.4462 | $3.4462 | 25m 15s | 23,882 | 6,834,373 | 31 | src/Collection.js (481 LOC) |
| openhands-glm-5-2-medium-prod-20260918-q05 | glm-5.2 | medium | 0.1112 | 16.9M/258.1K/135.1K/15.9M | 594 | 594 | $6.6824 | $6.6824 | 1h 20m 28s | 630 | 194,009 | 24 | src-rs/runner.rs (553 LOC) |
| openhands-luna-high-20260916-r2 | gpt-5.6-luna | high | 0.0835 | 842.0K/15.6K/0/793.0K | 64 | 64 | $0.3168 | $0.0465 | 4m 28s | 22 | 103 | 24 | src/Collection.js (481 LOC) |
| openhands-luna-high-dev-20260918 | gpt-5.6-luna | high | 0.0835 | 696.7K/16.7K/0/656.2K | 72 | 72 | $0.3000 | $0.0507 | 4m 59s | 624 | 200 | 24 | src/Collection.js (481 LOC) |
| openhands-luna-high-20260916-r4 | gpt-5.6-luna | high | 0.0821 | 4.0M/33.6K/0/3.8M | 96 | 96 | $1.0952 | $0.1399 | 10m 27s | 10 | 489 | 24 | src/Collection.js (481 LOC) |
| openhands-luna-medium-20260915-r2 | gpt-5.6-luna | medium | 0.0835 | 564.4K/6.1K/0/531.6K | 33 | 33 | $0.1681 | $0.0282 | 2m 05s | 7 | 74 | 24 | src/Collection.js (481 LOC) |
| openhands-luna-medium-20260916 | gpt-5.6-luna | medium | 0.0835 | 484.6K/5.9K/0/456.4K | 30 | 30 | $0.1510 | $0.0237 | 2m 37s | 27 | 114 | 24 | src/Collection.js (481 LOC) |
| openhands-luna-medium-prod-dev-20260918 | gpt-5.6-luna | medium | 0.0835 | 371.7K/4.9K/0/350.1K | 37 | 37 | $0.1199 | $0.0199 | 1m 58s | 622 | 7,576 | 24 | src/Collection.js (481 LOC) |
| openhands-sol-high-20260916 | gpt-5.6-sol | high | 0.3258 | 9.2M/64.7K/0/8.7M | 151 | 151 | $2.3142 | $5.5666 | 24m 13s | 1,820 | 357,009 | 27 | bridge/Collection.js (481 LOC) |
| openhands-sol-high-20260916-r2 | gpt-5.6-sol | high | 0.2687 | 4.6M/54.3K/21.2K/4.5M | 118 | 118 | $1.2455 | $3.4439 | 22m 12s | 389 | 3,583 | 26 | bridge/api/Collection.js (481 LOC) |
| openhands-sol-high-prod-20260919-r1 | gpt-5.6-sol | high | 0.2670 | 9.1M/143.8K/54.6K/8.5M | 319 | 319 | $3.2190 | $9.1462 | 56m 29s | 2,162 | 218,056 | 26 | bridge/transform-host.js (3,037 LOC) |
| openhands-sol-medium-20260917-r4 | gpt-5.6-sol | medium | 0.2793 | 1.9M/32.7K/8.9K/1.9M | 80 | 80 | $0.6403 | $1.7220 | 11m 59s | 760 | 5,909 | 24 | rust/src/main.rs (536 LOC) |
| openhands-sol-medium-20260917-r6 | gpt-5.6-sol | medium | 0.2397 | 1.4M/30.2K/8.1K/1.3M | 47 | 47 | $0.5454 | $1.4418 | 14m 04s | 626 | 3,005 | 24 | rust/main.rs (521 LOC) |
| openhands-sol-medium-prod-20260918-r3 | gpt-5.6-sol | medium | 0.1112 | 2.1M/35.6K/9.6K/2.0M | 88 | 88 | $0.7536 | $2.1006 | 17m 21s | 656 | 879 | 24 | src/Collection.js (481 LOC) |
| openhands-terra-high-prod-dev-20260918 | gpt-5.6-terra | high | 0.1216 | 1.4M/31.0K/0/1.3M | 65 | 65 | $0.5879 | $0.9113 | 8m 43s | 87 | 893 | 24 | rust/src/main.rs (486 LOC) |
| openhands-terra-high-20260916-r4 | gpt-5.6-terra | high | 0.0835 | 554.9K/12.0K/0/521.0K | 37 | 37 | $0.2271 | $0.3551 | 4m 19s | 22 | 481 | 24 | src/Collection.js (481 LOC) |
| openhands-terra-high-20260915-r2 | gpt-5.6-terra | high | 0.0789 | 669.2K/13.7K/0/628.3K | 44 | 44 | $0.2669 | $0.4007 | 7m 07s | 69 | 386 | 24 | src/Collection.js (481 LOC) |
| openhands-terra-medium-20260916-r3 | gpt-5.6-terra | medium | 0.0835 | 447.6K/7.6K/0/420.3K | 26 | 26 | $0.1627 | $0.2727 | 3m 04s | 29 | 1,260 | 24 | src/Collection.js (481 LOC) |
| openhands-terra-medium-dev-20260919-r1 | gpt-5.6-terra | medium | 0.0835 | 442.9K/8.1K/2.3K/415.9K | 35 | 35 | $0.1666 | $0.2478 | 6m 53s | 64 | 519 | 24 | src/Collection.js (481 LOC) |
| openhands-terra-medium-dev-20260918 | gpt-5.6-terra | medium | 0.0668 | 501.0K/8.4K/1.9K/470.3K | 39 | 39 | $0.1811 | $0.2715 | 2m 51s | 615 | 485 | 24 | src/Collection.js (481 LOC) |
| openhands-grok-4-5-high-prod-20260918 | grok-4.5 | high | 0.2791 | 5.1M/98.0K/27.9K/4.6M | 106 | 106 | $6.0277 | $3.0139 | 29m 22s | 10,147 | 2,866,990 | 31 | rust/src/args.rs (828 LOC) |
| openhands-grok-4-5-high-prod-20260919-r2 | grok-4.5 | high | 0.2791 | 2.9M/56.1K/10.6K/2.6M | 71 | 71 | $3.4936 | $1.7468 | 19m 24s | 7,074 | 2,284,689 | 31 | rust/src/args.rs (756 LOC) |
| openhands-grok-4-5-high-20260917-r2 | grok-4.5 | high | 0.2774 | 2.7M/50.7K/7.8K/2.5M | 45 | 45 | $2.8217 | — | 15m 04s | 80 | 70,269 | 36 | rust/src/args.rs (899 LOC) |
| openhands-1789798211 | grok-4.5 | medium | 0.2557 | 3.9M/66.8K/10.6K/3.7M | 60 | 60 | $3.8411 | $1.9205 | 18m 51s | 5,530 | 1,795,460 | 37 | rust/src/args.rs (770 LOC) |
| openhands-grok-4-5-medium-20260917 | grok-4.5 | medium | 0.2534 | 3.6M/55.5K/19.2K/3.3M | 56 | 56 | $4.1232 | — | 22m 49s | 6,227 | 2,203,218 | 30 | crates/jscodeshift/src/args.rs (731 LOC) |
| openhands-grok-4-5-medium-prod-20260919 | grok-4.5 | medium | 0.2501 | 2.7M/46.7K/13.0K/2.5M | 58 | 58 | $3.1368 | $1.5684 | 14m 35s | 6,117 | 2,216,205 | 36 | rust-src/runner.rs (490 LOC) |
| openhands-grok-4-6-high-dev-20260918 | grok-4.6 | high | 0.1147 | 16.8M/859.0K/0/15.8M | 2,134 | 2,134 | $29.9964 | — | 2h 52m 59s | 113 | 2,739 | 27 | src/Collection.js (481 LOC) |
| openhands-grok-4-6-high-dev-20260920-r1 | grok-4.6 | high | 0.1112 | 52.5M/2.5M/0/0 | 7197 | 7,197 | $240.5868 | — | 6h 00m 04s | 689 | 350,969 | 29 | rust/args.rs (669 LOC) |
| openhands-grok-4-6-medium-20260915 | grok-4.6 | medium | 0.1476 | 10.3M/171.3K/0/9.7M | 183 | 183 | $14.1259 | — | 37m 11s | 5,052 | 1,775,202 | 31 | src/Collection.js (481 LOC) |
| openhands-grok-4-6-medium-20260916-r2 | grok-4.6 | medium | 0.1476 | 5.4M/275.9K/0/5.1M | 150 | 150 | $9.7102 | — | 52m 31s | 1,985 | 359,624 | 27 | src/Collection.js (481 LOC) |
| openhands-grok-4-6-medium-dev-20260921 | grok-4.6 | medium | 0.0280 | — | — | — | — | — | 0m 00s | 1 | 12 | 24 | src/Collection.js (481 LOC) |
| openhands-kimi-k3-high-20260916-r3 | kimi-k3 | high | 0.3138 | 22.0M/133.2K/75.8K/22.0M | 182 | 182 | $8.5976 | — | 48m 06s | 1,108 | 355,985 | 26 | rust/src/glob.rs (803 LOC) |
| openhands-kimi-k3-high-20260916-r6 | kimi-k3 | high | 0.2843 | 7.1M/78.3K/37.5K/7.0M | 107 | 107 | $3.5443 | — | 35m 50s | 561 | 8,388 | 28 | rust/src/cli.rs (821 LOC) |
| openhands-kimi-k3-high-20260916-r4 | kimi-k3 | high | 0.2722 | 17.7M/118.3K/54.6K/17.7M | 164 | 164 | $7.1027 | — | 40m 16s | 602 | 6,651 | 23 | rust/src/args.rs (899 LOC) |
| openhands-kimi-k3-medium-20260917-r6 | kimi-k3 | medium | 0.3034 | 3.1M/39.5K/12.6K/3.0M | 85 | 85 | $1.7634 | — | 13m 37s | 1,676 | 696,037 | 26 | rust/runner.rs (548 LOC) |
| openhands-kimi-k3-medium-20260917-r4 | kimi-k3 | medium | 0.2670 | 2.9M/33.4K/10.5K/2.9M | 85 | 85 | $1.3766 | — | 12m 50s | 4,421 | 1,126,689 | 28 | src/Collection.js (481 LOC) |
| openhands-kimi-k3-medium-20260916-r3 | kimi-k3 | medium | 0.1476 | 2.6M/43.6K/20.2K/2.6M | 71 | 71 | $1.6045 | — | 16m 49s | 3,896 | 1,162,284 | 28 | src/Collection.js (481 LOC) |
| openhands-1789661737 | minimax-m3 | high | 0.1268 | 24.1M/116.2K/2.3K/22.7M | 497 | 497 | $7.6723 | $1.9181 | 1h 18m 25s | 4,292 | 1,598,959 | 29 | src/Collection.js (481 LOC) |
| openhands-minimax-m3-high-prod-20260917 | minimax-m3 | high | 0.1147 | 21.0M/108.0K/1.6K/20.2M | 494 | 494 | $6.3449 | $1.5862 | 58m 57s | 1,715 | 350,677 | 27 | src/rust/arg_parser.rs (528 LOC) |
| openhands-minimax-m3-high-prod-20260919 | minimax-m3 | high | 0.1147 | 7.7M/85.4K/3.5K/7.3M | 313 | 313 | $2.7063 | $0.6766 | 36m 31s | 4,064 | 1,030,467 | 36 | src/runner.rs (492 LOC) |
| openhands-1789798212 | minimax-m3 | medium | 0.1233 | 7.5M/90.4K/3.7K/7.2M | 345 | 345 | $2.5556 | $0.6389 | 22m 30s | 1,058 | 360,333 | 17 | src/Collection.js (481 LOC) |
| openhands-minimax-m3-medium-prod-20260919-r4 | minimax-m3 | medium | 0.1129 | 13.7M/123.8K/7.1K/13.0M | 581 | 581 | $4.5253 | $1.1313 | 34m 34s | 5,361 | 1,640,850 | 33 | src/Collection.js (481 LOC) |
| openhands-minimax-m3-medium-prod-20260919-r5 | minimax-m3 | medium | 0.1112 | 7.9M/92.8K/3.8K/7.3M | 363 | 363 | $2.9169 | $0.7292 | 33m 35s | 2,088 | 457,710 | 31 | rust-src/args.rs (851 LOC) |
| openhands-qwen-3-8-high-prod-20260919-q08 | qwen-3.8 | high | 0.0904 | 18.9M/2.6M/2.4M/15.6M | 466 | 466 | $53.1168 | $25.8347 | 6h 00m 05s | 2,674 | 1,555,081 | 31 | src/Collection.js (481 LOC) |
| openhands-qwen-3-8-high-prod-20260920-r1 | qwen-3.8 | high | 0.0696 | 22.9M/2.3M/2.2M/20.0M | 511 | 511 | $59.6924 | $24.6430 | 6h 00m 05s | 3,980 | 1,735,297 | 24 | src/Collection.js (481 LOC) |
| openhands-qwen-3-8-high-prod-20260918-q04 | qwen-3.8 | high | 0.0280 | 39.0M/2.9M/2.7M/33.7M | 1016 | 1,016 | $95.4236 | $36.4197 | 6h 00m 04s | 2,601 | 1,297,202 | 30 | src/Collection.js (481 LOC) |

Rows: 71 scored candidate runs.
