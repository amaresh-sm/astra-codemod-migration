# Private verification

This directory contains the private jscodeshift library migration verifier. It exercises the public
CLI and JavaScript transform API as a black box, using the upstream behavior baseline and
additional cases for worker scheduling, stdin, parser selection, dry runs, reporting, failures,
source preservation, lifecycle setup, package exports, core plugins, collection extensions,
template generation, and Rust entrypoint compatibility.

Legacy planner proof artifacts remain in this worktree for historical calibration only. They are
not used by the runner verifier.

## Rust ownership boundary

The verifier permits JavaScript only at the compatibility boundary needed to execute customer
transforms: `index.js`, `rust-compat.js`, `rust-compat-worker.js`, and an optional
`bin/jscodeshift.js` launcher. Ownership probes stage a disposable copy of the candidate, remove
all other JavaScript/TypeScript source files, and run the same black-box transforms. A Node preload
tracer records child worker module loads, while a launcher override records the compiled Rust
process. Any package-relative source module outside the allowlist, or any probe that does not
execute the native runner, fails the ownership criterion.

The exact-copy fingerprint check remains as a diagnostic for retained upstream source, but it is
not the primary ownership proof. The removal-and-trace probes are deliberately independent per
parser, core, worker, and package boundary.
