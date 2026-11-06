#!/usr/bin/env bash
# Base layer of envkit.python-uv: toolchains only, never repository-specific work.
# Installs uv from Astral's installer when it is missing, then a uv-managed Python 3.12.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
uv python install 3.12
uv --version
