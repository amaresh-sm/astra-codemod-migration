FROM mcr.microsoft.com/playwright:v1.61.1-noble AS browser-toolchain
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        jq \
        postgresql \
        postgresql-client \
        psmisc \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home verifier
COPY --from=browser-toolchain /ms-playwright/ /ms-playwright/
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN npm install --global --ignore-scripts --no-audit --no-fund @playwright/test@1.61.1 \
    && npx playwright install-deps chromium \
    && python3 -m venv /opt/verifier-venv \
    && /opt/verifier-venv/bin/pip install --no-cache-dir playwright==1.61.0 \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/verifier-venv/bin:${PATH}"
ENV DATABASE_URL="postgresql://arena:arena@127.0.0.1:5432/arena?sslmode=disable"
WORKDIR /work
COPY environment/verifier/entrypoint.sh /usr/local/bin/astra-verify
RUN chmod 0555 /usr/local/bin/astra-verify \
    && mkdir -p /input/candidate /input/verifier /output /work/candidate \
    && ln -s /work/candidate /workspace \
    && chown -R verifier:verifier /input /output /work

USER root
ENTRYPOINT ["/usr/local/bin/astra-verify"]
