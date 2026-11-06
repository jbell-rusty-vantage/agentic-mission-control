#!/usr/bin/env bash
# Base layer for Cursor Cloud agents on this repo (Mission Control kit envkit.mission-control-dev@1).
# Runs at environment Build time against the default branch: toolchain and dependencies only.
# Per-mission setup belongs to the mission layer (.mission/setup/run), run from cloud-start.sh.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

uv sync --frozen --group biotech --group dbcontract
docker compose config --quiet

echo "Mission Control dependencies installed; Docker Compose configuration is valid."
