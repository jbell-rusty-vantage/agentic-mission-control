#!/usr/bin/env bash
# Base layer of envkit.knowledge-research: PDF and OCR tools from the distribution, uv and
# Python 3.12 (installed when missing) and the base image's Node.js. Toolchains only.
set -euo pipefail

if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends poppler-utils tesseract-ocr
fi
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
uv python install 3.12
node --version
