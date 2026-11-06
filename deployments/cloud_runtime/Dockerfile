# Build from the repository root. Linux/amd64 manifests verified 2026-10-11.
# Only explicit source paths enter the image; no .env, user workspace, or credentials.
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.23@sha256:dd2385ac82b9aff6489344ec2b22916db986eb135454d030bce3038c7598a689
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# uv resolves local optional package metadata even when those groups aren't installed.
COPY integrations/biotech/pyproject.toml integrations/biotech/README.md ./integrations/biotech/
COPY packages/mission-control-db-contract/pyproject.toml packages/mission-control-db-contract/README.md ./packages/mission-control-db-contract/
RUN uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MISSION_CONTROL_HOME=/etc/mission-control
COPY --from=build /opt/venv /opt/venv
WORKDIR /etc/mission-control
USER 10001:10001
STOPSIGNAL SIGTERM
CMD ["uvicorn", "mission_control.bootstrap.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
# Extend this image with reviewed public configuration, JWKS, a runtime-options
# factory, and digest-verified capability assets. Inject secret values only at runtime.
