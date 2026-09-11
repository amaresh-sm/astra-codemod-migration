#!/usr/bin/env bash
set -euo pipefail
root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
binary="${JSCODESHIFT_BINARY:-$root/rust/target/release/jscodeshift}"
if [[ ! -x "$binary" ]]; then
  cargo build --quiet --release --manifest-path "$root/rust/Cargo.toml"
fi
exec "$binary" --package-root "$root" "$@"
