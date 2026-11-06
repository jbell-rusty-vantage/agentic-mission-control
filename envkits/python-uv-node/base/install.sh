#!/usr/bin/env bash
# Base layer of envkit.python-uv-node: uv and Python 3.12 (installed when missing) plus the
# base image's Node.js 22 and npm. Toolchains only, never repository-specific work.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
uv python install 3.12
uv --version
node --version
npm --version
