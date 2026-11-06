#!/usr/bin/env bash
# Base layer of envkit.node: Node.js 22 and npm come from the base image; this checks them.
set -euo pipefail

node --version
npm --version
