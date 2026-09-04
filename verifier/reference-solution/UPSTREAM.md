# Upstream context

The option names and traversal responsibilities are a small, self-contained adaptation of the
runner in [facebook/jscodeshift](https://github.com/facebook/jscodeshift). The benchmark fixture
does not vendor its dependency tree. The reference implementation keeps the JavaScript transform
API compatible while moving the runner implementation to Rust. The migration is judged by
externally observable behavior; it is not a request to rewrite user transforms or enforce a
particular internal AST architecture.
