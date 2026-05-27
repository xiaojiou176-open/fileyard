ARG NODE_RUNTIME_IMAGE=node:24.8.0-bullseye@sha256:1f01014be94e1bbd6687191b5e33e376b8bb1a48abf9c42560a26c812587fdfb
ARG DEVCONTAINER_BASE_IMAGE=mcr.microsoft.com/devcontainers/python:1-3.11-bullseye@sha256:ae5708357f39cf7fd7d8b8ac856dffa3525fbabd008e30e7562749b2cef619d5
ARG GITLEAKS_VERSION=8.24.2
ARG GITLEAKS_SHA256_AMD64=fa0500f6b7e41d28791ebc680f5dd9899cd42b58629218a5f041efa899151a8e
ARG GITLEAKS_SHA256_ARM64=574a6d52573c61173add7ddb5e3cc68c0e82cb0735818a1eeb9a0a2de1643fbc

FROM ${NODE_RUNTIME_IMAGE} AS node_runtime
FROM ${DEVCONTAINER_BASE_IMAGE}

ARG GITLEAKS_VERSION
ARG GITLEAKS_SHA256_AMD64
ARG GITLEAKS_SHA256_ARM64
ARG TARGETARCH

LABEL org.opencontainers.image.source="https://github.com/xiaojiou176-open/fileyard"

RUN rm -f /etc/apt/sources.list.d/yarn.list /etc/apt/sources.list.d/yarn.list.save

# Import Node runtime from a digest-pinned upstream image to avoid floating apt repository installs.
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node_runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node_runtime /usr/local/include/node /usr/local/include/node
COPY tooling/requirements-pip.lock.txt /tmp/organizer-build/requirements-pip.lock.txt
COPY tooling/requirements.lock.txt /tmp/organizer-build/requirements.lock.txt
COPY tooling/requirements-dev.lock.txt /tmp/organizer-build/requirements-dev.lock.txt

RUN set -eux; \
    ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm; \
    ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx; \
    ln -sf ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack; \
    printf '%s\n' \
      'Acquire::Retries "5";' \
      'Acquire::http::Timeout "30";' \
      'Acquire::https::Timeout "30";' \
      > /etc/apt/apt.conf.d/80-network-retries; \
    for attempt in 1 2 3; do \
      apt-get update && break; \
      if [ "$attempt" -eq 3 ]; then exit 1; fi; \
      sleep $((attempt * 5)); \
    done; \
    for attempt in 1 2 3; do \
      apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        ripgrep \
        libdbus-1-3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libatspi2.0-0 \
        libcups2 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libxkbcommon0 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 && break; \
      if [ "$attempt" -eq 3 ]; then exit 1; fi; \
      sleep $((attempt * 5)); \
    done; \
    case "${TARGETARCH:-amd64}" in \
      amd64) GITLEAKS_ARCHIVE="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"; GITLEAKS_SHA256="$GITLEAKS_SHA256_AMD64" ;; \
      arm64) GITLEAKS_ARCHIVE="gitleaks_${GITLEAKS_VERSION}_linux_arm64.tar.gz"; GITLEAKS_SHA256="$GITLEAKS_SHA256_ARM64" ;; \
      *) echo "Unsupported TARGETARCH for gitleaks: ${TARGETARCH:-unknown}" >&2; exit 1 ;; \
    esac; \
    curl -sSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${GITLEAKS_ARCHIVE}" \
      -o /tmp/gitleaks.tar.gz; \
    echo "${GITLEAKS_SHA256}  /tmp/gitleaks.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/gitleaks.tar.gz -C /tmp gitleaks; \
    install -m 0755 /tmp/gitleaks /usr/local/bin/gitleaks; \
    python -m venv /opt/fileyard-ci-venv; \
    /opt/fileyard-ci-venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r /tmp/organizer-build/requirements-pip.lock.txt; \
    /opt/fileyard-ci-venv/bin/python -m pip install --require-hashes -r /tmp/organizer-build/requirements.lock.txt; \
    awk 'BEGIN {emit=0} /^setuptools==/ {emit=1} emit {print} emit && /^    # via/ {exit}' \
      /tmp/organizer-build/requirements-dev.lock.txt > /tmp/organizer-build/setuptools-bootstrap.txt; \
    test -s /tmp/organizer-build/setuptools-bootstrap.txt; \
    /opt/fileyard-ci-venv/bin/python -m pip install --require-hashes -r /tmp/organizer-build/setuptools-bootstrap.txt; \
    /opt/fileyard-ci-venv/bin/python -m pip install --require-hashes -r /tmp/organizer-build/requirements-dev.lock.txt; \
    cat /tmp/organizer-build/requirements.lock.txt /tmp/organizer-build/requirements-dev.lock.txt | sha256sum | awk '{print $1}' > /opt/fileyard-ci-venv/.movi_req_hash; \
    node -v; \
    npm -v; \
    gitleaks version; \
    rm -rf /tmp/gitleaks /tmp/gitleaks.tar.gz /tmp/organizer-build; \
    rm -rf /var/lib/apt/lists/*
