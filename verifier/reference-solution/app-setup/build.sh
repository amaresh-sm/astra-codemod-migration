#!/usr/bin/env bash
set -euo pipefail
cargo build --release --manifest-path native/planner/Cargo.toml
node --test test/planner.test.js
