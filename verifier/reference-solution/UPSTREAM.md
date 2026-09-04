# Upstream context

The option names and traversal responsibilities are a small, self-contained adaptation of the
runner in [facebook/jscodeshift](https://github.com/facebook/jscodeshift). The benchmark fixture
does not vendor its dependency tree: the migration target is the file-selection subsystem, not the
AST transform engine or the transform API.
