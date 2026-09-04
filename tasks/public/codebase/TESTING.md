# Test and fixture layout

The upstream test layout is intentionally preserved:

- `src/__tests__/` covers core collections, worker behavior, argument parsing, ignore handling,
  templates, and utilities.
- `src/__testfixtures__/` contains transform input/output fixtures used by the source tests.
- `src/collections/__tests__/` covers collection-specific helpers.
- `parser/__tests__/` covers TypeScript/TSX parser behavior.
- `bin/__tests__/` covers the command-line entry point.
- `sample/__tests__/` and `sample/__testfixtures__/` cover the documented sample transform.

Run the upstream suite from this directory with:

```bash
yarn test
```

The runner migration must preserve these observable behaviors even when the implementation moves
from JavaScript to Rust.
