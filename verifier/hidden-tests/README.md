# Runner verification checks

Private checks for this task belong here and should invoke the submitted `jscodeshift` command as
a black box. Organize them by observable behavior: CLI compatibility, file selection, transform
API compatibility, worker scheduling, dry-run/write semantics, reporting, and failure handling.
Keep upstream test fixtures and any expected outputs here when they are used as verification
oracles; do not expose evaluator-only scenarios through `tasks/public/`.
