# Mission Control application images: one target per process role, built from the uv lockfile.
#
#   docker build -f deployments/docker/Dockerfile --target api    -t mission-control-api:local .
#   docker build -f deployments/docker/Dockerfile --target worker -t mission-control-worker:local .
#
# Build from the repository root (`.dockerignore` keeps `.env`, `.scratch`, tests and docs out).
# Only explicit source paths enter the image: no `.env`, deployment file, key or credential.
# Configuration arrives at run time as an env file and a mounted deployment directory
# (`compose.yml` beside this file); MISSION_CONTROL_HOME is that mount, which holds no `.env`.
#
# The worker target adds a Node runtime: the pinned capability tools (the agent browser and the
# reviewed MCP modules of `infra/capability-pins`) run on it. Their bytes are not in this image;
# the capability resource owner is mounted (MISSION_CONTROL_WORKSPACE_ROOT).
#
# Base image digests are the Linux/amd64-verified pins of deployments/cloud_runtime/Dockerfile
# (2026-10-11); the Node index digest was read from the registry on 2026-11-15.
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.23@sha256:dd2385ac82b9aff6489344ec2b22916db986eb135454d030bce3038c7598a689
ARG NODE_IMAGE=node:24-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54

FROM ${UV_IMAGE} AS uv
FROM ${NODE_IMAGE} AS node

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /build
# Dependencies first: this layer is reused until the lockfile changes. uv resolves the metadata
# of the local optional packages even though their groups are not installed.
COPY pyproject.toml uv.lock README.md ./
COPY integrations/biotech/pyproject.toml integrations/biotech/README.md ./integrations/biotech/
COPY packages/mission-control-db-contract/pyproject.toml packages/mission-control-db-contract/README.md ./packages/mission-control-db-contract/
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MISSION_CONTROL_HOME=/var/lib/mission-control
RUN groupadd --gid 10001 mission-control \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /var/lib/mission-control \
        --shell /usr/sbin/nologin mission-control \
    && install -d -o 10001 -g 10001 /var/lib/mission-control
COPY --from=build /opt/venv /opt/venv
WORKDIR /var/lib/mission-control
USER 10001:10001
STOPSIGNAL SIGTERM

FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=90s --retries=6 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4).status == 200 else 1)"]
CMD ["mission-control", "api", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker
COPY --from=node /usr/local/bin/node /usr/local/bin/node
CMD ["mission-control", "worker"]
