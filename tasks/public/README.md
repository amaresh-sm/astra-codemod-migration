# Candidate package

This package contains a pinned source snapshot of the jscodeshift codemod toolkit and its public
compatibility materials. Implement the requested migration using this codebase; do not assume
network access or a separately installed jscodeshift package.

The source tree is under `codebase/`. Its existing tests and fixtures remain with the upstream
layout (`src/__tests__/`, `src/__testfixtures__/`, `bin/__tests__/`, `parser/__tests__/`, and
`sample/__tests__/`). They describe existing behavior; additional verification tests are maintained
privately by the task harness.

Include an `app-setup/manifest.json` in the completed workspace describing how to build, reset, and
start the CLI. Put lifecycle commands under `commands` as non-empty argument arrays; this migration
does not require an HTTP readiness URL.

```json
{
  "contractVersion": "1.0",
  "commands": {
    "build": ["bash", "app-setup/build.sh"],
    "reset": ["bash", "app-setup/reset.sh"],
    "start": ["bash", "app-setup/start.sh"]
  }
}
```
