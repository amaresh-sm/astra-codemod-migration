FROM node:22-bookworm-slim

ENV RUSTUP_HOME="/opt/rustup"
ENV CARGO_HOME="/opt/cargo"
ENV PATH="/opt/cargo/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        build-essential \
        postgresql \
        postgresql-client \
        psmisc \
        python3 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/rustup /opt/cargo \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --profile minimal --default-toolchain stable --no-modify-path \
        --default-host aarch64-unknown-linux-gnu \
    && chmod -R a+rX /opt/rustup /opt/cargo \
    && ln -s /opt/cargo/bin/cargo /usr/local/bin/cargo \
    && ln -s /opt/cargo/bin/rustc /usr/local/bin/rustc \
    && useradd --create-home runner

ENV DATABASE_URL="postgresql://arena:arena@127.0.0.1:5432/arena?sslmode=disable"
WORKDIR /workspace
COPY environment/candidate-runtime/entrypoint.sh /usr/local/bin/astra-candidate-runtime
RUN chmod 0555 /usr/local/bin/astra-candidate-runtime

USER root
ENTRYPOINT ["/usr/local/bin/astra-candidate-runtime"]
