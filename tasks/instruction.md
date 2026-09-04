# Migrate the jscodeshift library to Rust

Migrate the complete first-party jscodeshift library from JavaScript to Rust while preserving all
externally observable behavior. The migration includes the CLI, argument handling, file discovery,
ignore rules, runner, workers, core API, collections, node matching, templates, parser adapters,
and package utilities. Keep existing JavaScript transforms working, including collection
traversal, builders, comments, formatting, and supported JavaScript, TypeScript, and TSX syntax.
Use the supplied source and public compatibility materials as the migration baseline. Additional
behavior is checked privately by the verifier. The public behavior requirements are defined in
`contracts/migration.contract.json`; use that contract as the authoritative compatibility target.

Internal implementation details may change, but the public CLI, transform API, outputs, errors,
options, file-writing behavior, and compatibility semantics must remain unchanged. Do not require
users to rewrite transforms.

Include `app-setup/manifest.json` in the completed workspace. It is the harness lifecycle handoff
for this CLI task: define non-empty argument arrays under `commands` for `build`, `reset`, and
`start`.

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
