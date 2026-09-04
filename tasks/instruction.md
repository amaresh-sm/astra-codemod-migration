# Migrate the jscodeshift runner and AST boundary to Rust

Migrate the complete jscodeshift command-line runner from JavaScript to Rust and move the
parse/transform/print boundary into the Rust implementation for the supported JavaScript,
TypeScript, and TSX syntax. Keep existing JavaScript transforms working through a compatibility
bridge, including collection traversal, builders, comments, and formatting. Use the supplied
source, tests, and fixtures as the compatibility baseline and ensure they continue to pass. The
public behavior requirements are defined in `contracts/migration.contract.json`; use that
contract as the authoritative compatibility target.

The migration is complete only when Rust owns file discovery, worker scheduling, parsing/printing,
and result aggregation; the bridge is limited to invoking the existing JavaScript transform API.
Do not replace the transform API or require users to rewrite transforms.

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
