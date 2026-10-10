# Build-runner image (ADR-0015): the workspace's locked web toolchain, installed once at image
# build time, so generated projects build with no network. Build from the repository root:
#   docker build -f services/build-runner/Dockerfile -t workspace-build-runner:local .
FROM node:22.12.0-bookworm-slim

WORKDIR /toolchain
# Generated projects pin exactly the versions in this lockfile (tested in codegen-react).
COPY apps/workspace-web/package.json apps/workspace-web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
    && npm cache clean --force \
    && chmod -R a-w /toolchain

COPY services/build-runner/container/build.sh /opt/runner/build.sh
USER node
WORKDIR /work
ENTRYPOINT ["/bin/sh", "/opt/runner/build.sh"]
