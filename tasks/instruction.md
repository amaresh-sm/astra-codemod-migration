# Migrate the jscodeshift runner to Rust

Migrate the complete jscodeshift command-line runner from JavaScript to Rust. Keep the existing
public CLI behavior and JavaScript/TypeScript transform compatibility. Use the supplied source,
tests, and fixtures as the compatibility baseline and ensure they continue to pass.

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
