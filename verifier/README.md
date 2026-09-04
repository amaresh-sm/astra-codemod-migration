# Private verification

This directory is reserved for the jscodeshift runner migration verifier. The final verifier will
exercise the public CLI and JavaScript transform API as a black box, using the upstream tests and
additional cases for worker scheduling, stdin, parser selection, dry runs, reporting, failures,
and compatibility.

The previous planner-only verifier artifacts are retained in this worktree until the new
runner-specific reference solution and private checks are authored. Do not score the new task with
those legacy artifacts.
