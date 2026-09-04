FROM node:22-bookworm-slim

ARG CODEX_VERSION=0.144.6
ARG CLAUDE_CODE_VERSION=latest

ENV RUSTUP_HOME="/opt/rustup"
ENV CARGO_HOME="/opt/cargo"
ENV PATH="/opt/cargo/bin:${PATH}"

# Codex uses the operating system trust store for its Rust HTTP client. The
# slim Node image includes Node's bundled roots but not the system CA bundle,
# which causes TLS failures against the provider endpoint.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/rustup /opt/cargo \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --profile minimal --default-toolchain stable --no-modify-path \
        --default-host aarch64-unknown-linux-gnu \
    && chmod -R a+rX /opt/rustup /opt/cargo \
    && ln -s /opt/cargo/bin/cargo /usr/local/bin/cargo \
    && ln -s /opt/cargo/bin/rustc /usr/local/bin/rustc

RUN npm install --global --ignore-scripts --no-audit --no-fund "@openai/codex@${CODEX_VERSION}" \
    && codex --version

# Claude Code is installed alongside Codex so the shared generator can select
# either provider without modifying the candidate workspace or image at runtime.
# Claude Code downloads its platform-native binary during postinstall.  Do not
# use --ignore-scripts here: it leaves the CLI wrapper installed but unusable.
RUN npm install --global --no-audit --no-fund "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && claude --version

RUN useradd --create-home runner
WORKDIR /work
COPY environment/candidate-generation/entrypoint.sh /usr/local/bin/astra-generate
RUN chmod 0555 /usr/local/bin/astra-generate \
    && mkdir -p /input /output /work/candidate \
    && chown -R runner:runner /input /output /work

USER runner
ENTRYPOINT ["/usr/local/bin/astra-generate"]
