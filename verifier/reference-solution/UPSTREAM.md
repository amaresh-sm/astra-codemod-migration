# Upstream context

The option names and traversal responsibilities are a small, self-contained adaptation of the
runner in [facebook/jscodeshift](https://github.com/facebook/jscodeshift). The benchmark fixture
does not vendor its dependency tree. The reference implementation keeps the JavaScript transform
API as a bridge, while the Rust side owns discovery, scheduling, parsing/printing boundaries, and
result aggregation. This is the compatibility shape required by the migration contract; it is not
a request to rewrite user transforms.
