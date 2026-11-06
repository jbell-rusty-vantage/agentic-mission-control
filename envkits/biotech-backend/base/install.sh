#!/usr/bin/env bash
# Base layer of envkit.biotech-backend: uv and Python 3.12 (installed when missing) and the
# read-only biotech-meta dependency beside the target repository (fast-forwarded only when
# clean on main), adopted from the retired Biotech backend cloud-install.sh. Toolchains and
# dependency repositories only: the locked environment and the Compose check are mission steps.
set -euo pipefail

project_root="$(git rev-parse --show-toplevel)"
meta_root="$(dirname "$project_root")/biotech-meta"

if [[ ! -d "$meta_root/.git" ]]; then
    git clone https://github.com/Overton77/biotech-meta.git "$meta_root"
elif [[ "$(git -C "$meta_root" branch --show-current)" == "main" ]] \
    && git -C "$meta_root" diff --quiet \
    && git -C "$meta_root" diff --cached --quiet; then
    git -C "$meta_root" pull --ff-only origin main
fi

if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
uv python install 3.12
uv --version
