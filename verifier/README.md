# Private verification

This directory contains the private jscodeshift runner migration verifier. It exercises the public
CLI and JavaScript transform API as a black box, using the upstream behavior baseline and
additional cases for worker scheduling, stdin, parser selection, dry runs, reporting, failures,
source preservation, lifecycle setup, and Rust entrypoint compatibility.

Legacy planner proof artifacts remain in this worktree for historical calibration only. They are
not used by the runner verifier.
