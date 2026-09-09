# Upstream context

The public behavior follows [facebook/jscodeshift](https://github.com/facebook/jscodeshift).
The reference package replaces its CLI, discovery, scheduling, lifecycle, and worker boundary
with a Cargo-built Rust executable. A small JavaScript compatibility boundary keeps existing
transforms and package-root calls usable without loading the original jscodeshift `src/`, parser,
or recast implementation. The migration is judged by the frozen black-box compatibility contract.
